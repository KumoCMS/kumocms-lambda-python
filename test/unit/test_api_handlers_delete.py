import json
import os
import sys
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

import delete


@pytest.fixture
def mock_s3():
    """Mock S3 client."""
    with patch.object(delete, "s3") as mock_s3_client:
        yield mock_s3_client


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource."""
    with patch.object(delete, "dynamodb") as mock_db:
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
    }


class TestDeleteHandler:
    """Tests for delete lambda_handler function."""

    def test_delete_success(self, mock_s3, mock_dynamodb, sample_document):
        """Test successful document deletion."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = delete.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert "successfully" in response_body["message"]

        # Verify S3 delete was called
        mock_s3.delete_object.assert_called_once_with(
            Bucket="test-s3-bucket", Key="documents/test-doc.pdf"
        )

        # Verify DynamoDB delete was called
        mock_dynamodb.delete_item.assert_called_once_with(Key={"document_id": "test-doc"})

    def test_delete_document_not_found(self, mock_s3, mock_dynamodb):
        """Test deleting non-existent document."""
        # Arrange
        event = {"pathParameters": {"id": "non-existent"}}

        mock_dynamodb.get_item.return_value = {}

        # Act
        result = delete.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 404
        response_body = json.loads(result["body"])
        assert "error" in response_body
        assert "not found" in response_body["error"].lower()

        # Verify no deletions were attempted
        assert mock_s3.delete_object.call_count == 0
        assert mock_dynamodb.delete_item.call_count == 0

    def test_delete_missing_id(self, mock_s3, mock_dynamodb):
        """Test deleting without ID in path."""
        # Arrange
        event = {"pathParameters": {}}

        # Act
        result = delete.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        response_body = json.loads(result["body"])
        assert "required" in response_body["error"]

    def test_delete_s3_error_still_deletes_db(self, mock_s3, mock_dynamodb, sample_document):
        """Test that S3 error doesn't stop DynamoDB deletion."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.return_value = {"Item": sample_document}
        mock_s3.delete_object.side_effect = Exception("S3 error")

        # Act
        result = delete.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200  # We chose to succeed even if S3 fails

        # Verify both were attempted
        mock_s3.delete_object.assert_called_once()
        mock_dynamodb.delete_item.assert_called_once_with(Key={"document_id": "test-doc"})

    def test_delete_error_handling(self, mock_s3, mock_dynamodb):
        """Test general error handling."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}

        mock_dynamodb.get_item.side_effect = Exception("Database is down")

        # Act
        result = delete.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 500
        response_body = json.loads(result["body"])
        assert "failed" in response_body["error"]

    def test_delete_url_encoded_id(self, mock_s3, mock_dynamodb, sample_document):
        """Test deleting with a URL encoded ID."""
        # Arrange
        event = {"pathParameters": {"id": "test%20doc"}}
        # The document in DB would have the decoded ID
        sample_document["document_id"] = "test doc"
        mock_dynamodb.get_item.return_value = {"Item": sample_document}

        # Act
        result = delete.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        mock_dynamodb.get_item.assert_called_once_with(Key={"document_id": "test doc"})
        mock_dynamodb.delete_item.assert_called_once_with(Key={"document_id": "test doc"})

    def test_delete_s3_key_missing_in_record(self, mock_s3, mock_dynamodb):
        """Test deleting when s3key is missing in DynamoDB record."""
        # Arrange
        event = {"pathParameters": {"id": "test-doc"}}
        # Record exists but has no s3key
        mock_dynamodb.get_item.return_value = {"Item": {"document_id": "test-doc"}}

        # Act
        result = delete.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        # S3 should NOT be called
        mock_s3.delete_object.assert_not_called()
        # DynamoDB SHOULD still be called
        mock_dynamodb.delete_item.assert_called_once_with(Key={"document_id": "test-doc"})


if __name__ == "__main__":
    pytest.main([__file__])
