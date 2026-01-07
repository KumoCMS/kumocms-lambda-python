import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Set AWS environment variables BEFORE importing any modules that use boto3
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["DOCUMENTS_TABLE"] = "test-documents-table"
os.environ["S3_BUCKET"] = "test-s3-bucket"

# Add the src/handlers/api and src/common directories to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "handlers" / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "common"))

import retrieve


@pytest.fixture
def mock_s3():
    """Mock S3 client."""
    with patch.object(retrieve, "s3") as mock_s3_client:
        yield mock_s3_client


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource."""
    with patch.object(retrieve, "dynamodb") as mock_db:
        mock_table = Mock()
        mock_db.Table.return_value = mock_table
        yield mock_table


@pytest.fixture
def sample_document():
    """Sample document from DynamoDB."""
    return {
        "document_id": "test-doc",
        "s3key": "documents/test-doc.pdf",
        "file_name": "test-doc.pdf",
        "content_type": "application/pdf",
        "size": Decimal("1024"),
        "timestamp": "2025-01-15T10:30:00Z",
        "storage_class": "STANDARD",
    }


class TestRetrieveHandler:
    """Tests for retrieve lambda_handler function."""

    def test_retrieve_by_document_id(self, mock_s3, mock_dynamodb, sample_document):
        """Test retrieving document by document_id."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.return_value = {"Item": sample_document}
        # mock_dynamodb.query.return_value = {'Items': []}  # Not used anymore
        mock_s3.head_object.return_value = {"StorageClass": "STANDARD"}
        mock_s3.generate_presigned_url.return_value = "https://presigned-url.example.com"

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["file_name"] == "test-doc.pdf"
        assert response_body["presigned_url"] == "https://presigned-url.example.com"
        assert response_body["size"] == 1024

        # Verify presigned URL was generated
        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": "test-s3-bucket",
                "Key": "documents/test-doc.pdf",
                "ResponseContentDisposition": 'attachment; filename="test-doc.pdf"',
            },
            ExpiresIn=60,
        )

    def test_retrieve_document_not_found(self, mock_s3, mock_dynamodb):
        """Test retrieving non-existent document."""
        # Arrange
        event = {"pathParameters": {"id": "non-existent"}}

        mock_dynamodb.get_item.return_value = {}  # Primary key returns empty

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 404
        response_body = json.loads(result["body"])
        assert "error" in response_body
        assert "not found" in response_body["error"].lower()

    def test_retrieve_url_encoded_id(self, mock_s3, mock_dynamodb, sample_document):
        """Test retrieving document with URL-encoded ID."""
        # Arrange
        document_id = "test%20doc"
        decoded_id = "test doc"
        event = {"pathParameters": {"id": document_id}}

        sample_document["document_id"] = decoded_id
        mock_dynamodb.get_item.return_value = {"Item": sample_document}
        mock_s3.head_object.return_value = {"StorageClass": "STANDARD"}
        mock_s3.generate_presigned_url.return_value = "https://presigned-url.example.com"

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["file_name"] == "test-doc.pdf"

    def test_list_all_documents(self, mock_s3, mock_dynamodb):
        """Test listing all documents (no path parameters)."""
        # Arrange
        event = {}  # No path parameters

        documents = [
            {
                "document_id": "doc1",
                "s3key": "documents/doc1.pdf",
                "file_name": "doc1.pdf",
                "size": Decimal("1024"),
            },
            {
                "document_id": "doc2",
                "s3key": "documents/doc2.pdf",
                "file_name": "doc2.pdf",
                "size": Decimal("2048"),
            },
        ]

        mock_dynamodb.scan.return_value = {"Items": documents}

        # Mock S3 head_object to confirm files exist
        mock_s3.head_object.return_value = {"StorageClass": "STANDARD", "ContentLength": 1024}

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert "documents" in response_body
        assert len(response_body["documents"]) == 2
        assert response_body["documents"][0]["document_id"] == "doc1"
        assert response_body["count"] == 2
        assert "limited to 100" in response_body["note"]
        mock_dynamodb.scan.assert_called_once_with(Limit=100)

    def test_list_documents_removes_orphaned_records(self, mock_s3, mock_dynamodb):
        """Test that orphaned DynamoDB records (no S3 file) are removed during list."""
        # Arrange
        event = {}

        documents = [
            {"document_id": "valid-doc", "s3key": "documents/valid.pdf", "file_name": "valid.pdf"},
            {
                "document_id": "orphaned-doc",
                "s3key": "documents/missing.pdf",
                "file_name": "missing.pdf",
            },
        ]

        mock_dynamodb.scan.return_value = {"Items": documents}

        # First file exists, second doesn't
        def head_object_side_effect(**kwargs):
            if "missing.pdf" in kwargs["Key"]:
                raise mock_s3.exceptions.NoSuchKey({}, "HeadObject")
            return {"StorageClass": "STANDARD"}

        mock_s3.head_object.side_effect = head_object_side_effect
        mock_s3.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert len(response_body["documents"]) == 1
        assert response_body["documents"][0]["document_id"] == "valid-doc"

        # Verify orphaned record was deleted
        mock_dynamodb.delete_item.assert_called_once_with(Key={"document_id": "orphaned-doc"})

    def test_list_documents_updates_storage_class(self, mock_s3, mock_dynamodb):
        """Test that storage class is updated from S3 if missing in DynamoDB."""
        # Arrange
        event = {}

        document = {
            "document_id": "doc1",
            "s3key": "documents/doc1.pdf",
            "file_name": "doc1.pdf",
            # Note: no storage_class field
        }

        mock_dynamodb.scan.return_value = {"Items": [document]}
        mock_s3.head_object.return_value = {"StorageClass": "GLACIER"}

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["documents"][0]["storage_class"] == "GLACIER"

    def test_list_documents_checks_restore_status(self, mock_s3, mock_dynamodb):
        """Test that restore status is checked from S3 metadata."""
        # Arrange
        event = {}

        document = {
            "document_id": "archived-doc",
            "s3key": "documents/archived.pdf",
            "file_name": "archived.pdf",
            "storage_class": "GLACIER",
        }

        mock_dynamodb.scan.return_value = {"Items": [document]}
        mock_s3.head_object.return_value = {
            "StorageClass": "GLACIER",
            "Restore": 'ongoing-request="false", expiry-date="Wed, 31 Dec 2025 23:59:59 GMT"',
        }

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["documents"][0]["restore_status"] == "restored"

    def test_retrieve_archived_file_fails(self, mock_s3, mock_dynamodb, sample_document):
        """Test that retrieving an archived file (not restored) returns 403."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}
        sample_document["storage_class"] = "GLACIER"
        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Mock S3 head_object to show it's archived and NOT being restored
        mock_s3.head_object.return_value = {
            "StorageClass": "GLACIER"
            # No 'Restore' key
        }

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 403
        response_body = json.loads(result["body"])
        assert "restore api" in response_body["message"].lower()

    def test_retrieve_restoration_in_progress(self, mock_s3, mock_dynamodb, sample_document):
        """Test that retrieving an archived file with restoration in progress returns 202."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}
        sample_document["storage_class"] = "GLACIER"
        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Mock S3 head_object to show restoration in progress
        mock_s3.head_object.return_value = {
            "StorageClass": "GLACIER",
            "Restore": 'ongoing-request="true"',
        }

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 202
        response_body = json.loads(result["body"])
        assert "in progress" in response_body["message"].lower()

    def test_retrieve_restored_file_success(self, mock_s3, mock_dynamodb, sample_document):
        """Test that retrieving an archived file that IS restored returns 200."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}
        sample_document["storage_class"] = "GLACIER"
        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Mock S3 head_object to show restoration complete
        mock_s3.head_object.return_value = {
            "StorageClass": "GLACIER",
            "Restore": 'ongoing-request="false"',
        }
        mock_s3.generate_presigned_url.return_value = "https://presigned.url"

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert "presigned_url" in response_body

    def test_retrieve_error_handling(self, mock_s3, mock_dynamodb):
        """Test error handling in retrieve."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.side_effect = Exception("DynamoDB error")

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 500
        response_body = json.loads(result["body"])
        assert "error" in response_body

    def test_retrieve_cors_headers(self, mock_s3, mock_dynamodb, sample_document):
        """Test that CORS headers are present in response."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.return_value = {"Item": sample_document}
        mock_s3.head_object.return_value = {"StorageClass": "STANDARD"}
        mock_s3.generate_presigned_url.return_value = "https://presigned-url.example.com"

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        headers = result["headers"]
        assert headers["Access-Control-Allow-Origin"] == "*"
        assert "Access-Control-Allow-Headers" in headers

    def test_retrieve_decimal_conversion(self, mock_s3, mock_dynamodb, sample_document):
        """Test that Decimal types are converted to int/float."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        # Use Decimal that converts to int
        sample_document["size"] = Decimal("2048")
        mock_dynamodb.get_item.return_value = {"Item": sample_document}
        mock_s3.head_object.return_value = {"StorageClass": "STANDARD"}
        mock_s3.generate_presigned_url.return_value = "https://presigned-url.example.com"

        # Act
        result = retrieve.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert isinstance(response_body["size"], (int, float))
        assert response_body["size"] == 2048


if __name__ == "__main__":
    pytest.main([__file__])
