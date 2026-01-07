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

import restore


@pytest.fixture
def mock_s3():
    """Mock S3 client."""
    with patch.object(restore, "s3") as mock_s3_client:
        yield mock_s3_client


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource."""
    with patch.object(restore, "dynamodb") as mock_db:
        mock_table = Mock()
        mock_db.Table.return_value = mock_table
        yield mock_table


@pytest.fixture
def sample_archived_document():
    """Sample archived document from DynamoDB."""
    return {
        "document_id": "archived-doc",
        "s3key": "documents/archived-doc.pdf",
        "file_name": "archived-doc.pdf",
        "content_type": "application/pdf",
        "size": Decimal("1024"),
        "storage_class": "GLACIER",
        "archived_date": "2025-01-10T10:00:00Z",
        "timestamp": "2025-01-01T10:30:00Z",
    }


class TestRestoreHandler:
    """Tests for restore lambda_handler function."""

    def test_restore_success_standard_tier(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test successful document restore with Standard tier."""
        # Arrange
        event = {
            "pathParameters": {"id": "archived-doc"},
            "body": json.dumps({"days": 5, "tier": "Standard"}),
        }

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "Document restore initiated successfully"
        assert response_body["restore_tier"] == "Standard"
        assert response_body["restore_days"] == 5
        assert response_body["restore_status"] == "in_progress"
        assert response_body["estimated_completion"] == "3-5 hours"

        # Verify S3 restore_object was called
        mock_s3.restore_object.assert_called_once()
        call_args = mock_s3.restore_object.call_args[1]
        assert call_args["Bucket"] == "test-s3-bucket"
        assert call_args["Key"] == "documents/archived-doc.pdf"
        assert call_args["RestoreRequest"]["Days"] == 5
        assert call_args["RestoreRequest"]["GlacierJobParameters"]["Tier"] == "Standard"

        # Verify DynamoDB was updated
        mock_dynamodb.update_item.assert_called_once()
        update_args = mock_dynamodb.update_item.call_args[1]
        assert update_args["Key"] == {"document_id": "archived-doc"}

    def test_restore_success_expedited_tier(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test successful document restore with Expedited tier."""
        # Arrange
        event = {
            "pathParameters": {"id": "archived-doc"},
            "body": json.dumps({"days": 1, "tier": "Expedited"}),
        }

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["restore_tier"] == "Expedited"
        assert response_body["estimated_completion"] == "1-5 minutes"

    def test_restore_success_bulk_tier(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test successful document restore with Bulk tier."""
        # Arrange
        event = {
            "pathParameters": {"id": "archived-doc"},
            "body": json.dumps({"days": 7, "tier": "Bulk"}),
        }

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["restore_tier"] == "Bulk"
        assert response_body["estimated_completion"] == "5-12 hours"

    def test_restore_default_parameters(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test restore with default parameters (1 day, Standard tier)."""
        # Arrange
        event = {"pathParameters": {"id": "archived-doc"}, "body": json.dumps({})}

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["restore_days"] == 1
        assert response_body["restore_tier"] == "Standard"

    def test_restore_missing_document_id(self, mock_s3, mock_dynamodb):
        """Test restore without document ID."""
        # Arrange
        event = {"pathParameters": {}, "body": json.dumps({"days": 5})}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        response_body = json.loads(result["body"])
        assert "error" in response_body
        assert "required" in response_body["message"].lower()

    def test_restore_document_not_found(self, mock_s3, mock_dynamodb):
        """Test restoring non-existent document."""
        # Arrange
        event = {"pathParameters": {"id": "non-existent"}, "body": json.dumps({"days": 5})}

        mock_dynamodb.get_item.return_value = {}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 404
        response_body = json.loads(result["body"])
        assert "error" in response_body
        assert "not found" in response_body["error"].lower()

    def test_restore_document_not_archived(self, mock_s3, mock_dynamodb):
        """Test restoring document that's not archived."""
        # Arrange
        event = {"pathParameters": {"id": "standard-doc"}, "body": json.dumps({"days": 5})}

        standard_doc = {
            "document_id": "standard-doc",
            "s3key": "documents/standard-doc.pdf",
            "storage_class": "STANDARD",
        }

        mock_dynamodb.get_item.return_value = {"Item": standard_doc}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 409
        response_body = json.loads(result["body"])
        assert "not archived" in response_body["error"].lower()

        # Verify restore_object was NOT called
        mock_s3.restore_object.assert_not_called()

    def test_restore_already_in_progress(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test restoring document with restore already in progress."""
        # Arrange
        event = {"pathParameters": {"id": "archived-doc"}, "body": json.dumps({"days": 5})}

        sample_archived_document["restore_status"] = "in_progress"
        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 409
        response_body = json.loads(result["body"])
        assert "in progress" in response_body["error"].lower()

        # Verify restore_object was NOT called
        mock_s3.restore_object.assert_not_called()

    def test_restore_invalid_days_too_low(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test restore with invalid days parameter (too low)."""
        # Arrange
        event = {"pathParameters": {"id": "archived-doc"}, "body": json.dumps({"days": 0})}

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        response_body = json.loads(result["body"])
        assert "invalid" in response_body["error"].lower()
        assert "days" in response_body["error"].lower()

    def test_restore_invalid_days_too_high(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test restore with invalid days parameter (too high)."""
        # Arrange
        event = {"pathParameters": {"id": "archived-doc"}, "body": json.dumps({"days": 366})}

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        response_body = json.loads(result["body"])
        assert "invalid" in response_body["error"].lower()

    def test_restore_invalid_tier(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test restore with invalid tier parameter."""
        # Arrange
        event = {
            "pathParameters": {"id": "archived-doc"},
            "body": json.dumps({"days": 5, "tier": "SuperFast"}),
        }

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        response_body = json.loads(result["body"])
        assert "invalid" in response_body["error"].lower()
        assert "tier" in response_body["error"].lower()

    def test_restore_s3_restore_already_in_progress_error(
        self, mock_s3, mock_dynamodb, sample_archived_document
    ):
        """Test handling S3 RestoreAlreadyInProgress error."""
        # Arrange
        event = {"pathParameters": {"id": "archived-doc"}, "body": json.dumps({"days": 5})}

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}
        mock_s3.restore_object.side_effect = Exception(
            "RestoreAlreadyInProgress: Restore is already in progress"
        )

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 409
        response_body = json.loads(result["body"])
        assert "already in progress" in response_body["error"].lower()

    def test_restore_s3_failure(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test handling S3 restore_object failure."""
        # Arrange
        event = {"pathParameters": {"id": "archived-doc"}, "body": json.dumps({"days": 5})}

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}
        mock_s3.restore_object.side_effect = Exception("S3 error")

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 500
        response_body = json.loads(result["body"])
        assert "error" in response_body
        assert "failed" in response_body["message"].lower()

        # Verify DynamoDB was NOT updated since S3 failed
        mock_dynamodb.update_item.assert_not_called()

    def test_restore_dynamodb_update_failure(
        self, mock_s3, mock_dynamodb, sample_archived_document
    ):
        """Test handling DynamoDB update failure after successful S3 restore."""
        # Arrange
        event = {"pathParameters": {"id": "archived-doc"}, "body": json.dumps({"days": 5})}

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}
        mock_dynamodb.update_item.side_effect = Exception("DynamoDB error")

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        # Should still return 200 even if DynamoDB update fails
        # (restore was initiated in S3)
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "Document restore initiated successfully"

    def test_restore_invalid_json_body(self, mock_s3, mock_dynamodb):
        """Test restore with invalid JSON in body."""
        # Arrange
        event = {"pathParameters": {"id": "archived-doc"}, "body": "not valid json"}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        response_body = json.loads(result["body"])
        assert "invalid json" in response_body["error"].lower()

    def test_restore_by_s3key(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test restoring document by s3key (now handled as document_id)."""
        # Arrange
        document_id = "documents/archived-doc.pdf"
        event = {"pathParameters": {"id": document_id}, "body": json.dumps({"days": 5})}

        # document_id is now the s3key
        sample_archived_document["document_id"] = document_id
        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "Document restore initiated successfully"

    def test_restore_url_encoded_id(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test restoring with URL-encoded document ID."""
        # Arrange
        s3key = "documents/my file.pdf"
        encoded_s3key = quote(s3key, safe="")
        event = {"pathParameters": {"id": encoded_s3key}, "body": json.dumps({"days": 5})}

        sample_archived_document["document_id"] = s3key
        sample_archived_document["s3key"] = s3key
        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200

    def test_restore_cors_headers(self, mock_s3, mock_dynamodb, sample_archived_document):
        """Test that CORS headers are present in response."""
        # Arrange
        event = {"pathParameters": {"id": "archived-doc"}, "body": json.dumps({"days": 5})}

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        headers = result["headers"]
        assert headers["Access-Control-Allow-Origin"] == "*"
        assert "Access-Control-Allow-Headers" in headers

    def test_restore_deep_archive_storage_class(
        self, mock_s3, mock_dynamodb, sample_archived_document
    ):
        """Test restoring document from DEEP_ARCHIVE."""
        # Arrange
        event = {
            "pathParameters": {"id": "archived-doc"},
            "body": json.dumps({"days": 5, "tier": "Standard"}),
        }

        sample_archived_document["storage_class"] = "DEEP_ARCHIVE"
        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "Document restore initiated successfully"

    def test_restore_response_includes_file_info(
        self, mock_s3, mock_dynamodb, sample_archived_document
    ):
        """Test that restore response includes file information."""
        # Arrange
        event = {"pathParameters": {"id": "archived-doc"}, "body": json.dumps({"days": 5})}

        mock_dynamodb.get_item.return_value = {"Item": sample_archived_document}

        # Act
        result = restore.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["file_name"] == "archived-doc.pdf"
        assert response_body["size"] == 1024
        assert "initiated_date" in response_body


if __name__ == "__main__":
    pytest.main([__file__])
