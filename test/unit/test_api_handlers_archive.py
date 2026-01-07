import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import quote

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

import archive


@pytest.fixture
def mock_s3():
    """Mock S3 client."""
    with patch.object(archive, "s3") as mock_s3_client:
        yield mock_s3_client


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource."""
    with patch.object(archive, "dynamodb") as mock_db:
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
        "storage_class": "STANDARD",
        "timestamp": "2025-01-15T10:30:00Z",
    }


class TestArchiveHandler:
    """Tests for archive lambda_handler function."""

    def test_archive_success(self, mock_s3, mock_dynamodb, sample_document):
        """Test successful document archiving."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "Document archived successfully"
        assert response_body["storage_class"] == "GLACIER"
        assert "archived_date" in response_body
        assert response_body["document_id"] == "test-doc"

        # Verify S3 copy_object was called to change storage class
        mock_s3.copy_object.assert_called_once()
        call_args = mock_s3.copy_object.call_args[1]
        assert call_args["Bucket"] == "test-s3-bucket"
        assert call_args["Key"] == "documents/test-doc.pdf"
        assert call_args["StorageClass"] == "GLACIER"

        # Verify DynamoDB was updated
        mock_dynamodb.update_item.assert_called_once()
        update_args = mock_dynamodb.update_item.call_args[1]
        assert update_args["Key"] == {"document_id": "test-doc"}

    def test_archive_by_s3key(self, mock_s3, mock_dynamodb, sample_document):
        """Test archiving document where the ID is an S3 key."""
        # Arrange
        document_id = "documents/test-doc.pdf"
        event = {"pathParameters": {"id": document_id}}

        sample_document["document_id"] = document_id
        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "Document archived successfully"

    def test_archive_missing_document_id(self, mock_s3, mock_dynamodb):
        """Test archiving without document ID."""
        # Arrange
        event = {"pathParameters": {}}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        response_body = json.loads(result["body"])
        assert "error" in response_body
        assert "required" in response_body["message"].lower()

    def test_archive_document_not_found(self, mock_s3, mock_dynamodb):
        """Test archiving non-existent document."""
        # Arrange
        event = {"pathParameters": {"id": "non-existent"}}

        mock_dynamodb.get_item.return_value = {}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 404
        response_body = json.loads(result["body"])
        assert "error" in response_body
        assert "not found" in response_body["error"].lower()

    def test_archive_already_archived_glacier(self, mock_s3, mock_dynamodb, sample_document):
        """Test archiving document that's already in GLACIER."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        sample_document["storage_class"] = "GLACIER"
        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 409
        response_body = json.loads(result["body"])
        assert "already archived" in response_body["error"].lower()
        assert response_body["storage_class"] == "GLACIER"

        # Verify S3 copy_object was NOT called
        mock_s3.copy_object.assert_not_called()

    def test_archive_already_archived_deep_archive(self, mock_s3, mock_dynamodb, sample_document):
        """Test archiving document that's already in DEEP_ARCHIVE."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        sample_document["storage_class"] = "DEEP_ARCHIVE"
        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 409
        response_body = json.loads(result["body"])
        assert "already archived" in response_body["error"].lower()

    def test_archive_url_encoded_id(self, mock_s3, mock_dynamodb, sample_document):
        """Test archiving with URL-encoded document ID."""
        # Arrange
        s3key = "documents/my file.pdf"
        encoded_s3key = quote(s3key, safe="")
        event = {"pathParameters": {"id": encoded_s3key}}

        sample_document["document_id"] = s3key
        sample_document["s3key"] = s3key
        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200

    def test_archive_s3_copy_failure(self, mock_s3, mock_dynamodb, sample_document):
        """Test handling S3 copy_object failure."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.return_value = {"Item": sample_document}
        mock_s3.copy_object.side_effect = Exception("S3 error")

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 500
        response_body = json.loads(result["body"])
        assert "error" in response_body
        assert "archive failed" in response_body["error"].lower()

        # Verify DynamoDB was NOT updated since S3 failed
        mock_dynamodb.update_item.assert_not_called()

    def test_archive_dynamodb_update_failure(self, mock_s3, mock_dynamodb, sample_document):
        """Test handling DynamoDB update failure after successful S3 archive."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.return_value = {"Item": sample_document}
        mock_dynamodb.update_item.side_effect = Exception("DynamoDB error")

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        # Should still return 200 even if DynamoDB update fails
        # (document was archived in S3)
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "Document archived successfully"

    def test_archive_dynamodb_retrieval_error(self, mock_s3, mock_dynamodb):
        """Test handling DynamoDB retrieval error."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.side_effect = Exception("Database error")

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 500
        response_body = json.loads(result["body"])
        assert "error" in response_body

    def test_archive_cors_headers(self, mock_s3, mock_dynamodb, sample_document):
        """Test that CORS headers are present in response."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        headers = result["headers"]
        assert headers["Access-Control-Allow-Origin"] == "*"

    def test_archive_preserves_metadata(self, mock_s3, mock_dynamodb, sample_document):
        """Test that document metadata is preserved during archive."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        sample_document["metadata"] = {"custom_field": "value"}
        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200

        # Verify metadata was passed to copy_object
        call_args = mock_s3.copy_object.call_args[1]
        assert call_args["Metadata"] == {"custom_field": "value"}
        assert call_args["MetadataDirective"] == "REPLACE"

    def test_archive_no_metadata(self, mock_s3, mock_dynamodb, sample_document):
        """Test archiving document without metadata field."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        # Remove metadata field
        if "metadata" in sample_document:
            del sample_document["metadata"]

        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200

        # Verify empty metadata was passed
        call_args = mock_s3.copy_object.call_args[1]
        assert call_args["Metadata"] == {}

    def test_archive_response_includes_file_info(self, mock_s3, mock_dynamodb, sample_document):
        """Test that archive response includes file information."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = archive.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["file_name"] == "test-doc.pdf"
        assert response_body["size"] == 1024


if __name__ == "__main__":
    pytest.main([__file__])
