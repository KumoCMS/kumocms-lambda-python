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

# Add the src/handlers/events and src/common directories to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "handlers" / "events"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "common"))

import restore_event_processor


@pytest.fixture
def mock_environment():
    """Mock environment variables."""
    with patch.dict(
        os.environ, {"DOCUMENTS_TABLE": "test-documents-table", "S3_BUCKET": "test-s3-bucket"}
    ):
        yield


@pytest.fixture
def mock_table():
    """Mock DynamoDB table."""
    mock_table = Mock()
    # Replace the module-level table with our mock
    original_table = restore_event_processor.table
    restore_event_processor.table = mock_table
    yield mock_table
    # Restore original table after test
    restore_event_processor.table = original_table


@pytest.fixture
def sample_restore_event():
    """Sample EventBridge event for restore completion."""
    return {
        "detail-type": "Object Restore Completed",
        "detail": {
            "bucket": {"name": "test-bucket"},
            "object": {"key": "documents/test-file.pdf"},
            "restore-expiry-time": "2025-12-31T23:59:59Z",
        },
    }


@pytest.fixture
def sample_restore_event_no_expiry():
    """Sample EventBridge event without restore expiry."""
    return {
        "detail-type": "Object Restore Completed",
        "detail": {"bucket": {"name": "test-bucket"}, "object": {"key": "documents/test-file.pdf"}},
    }


class TestHandleRestoreFile:
    """Tests for handle_restore_file function."""

    def test_handle_restore_file_with_expiry(self, mock_table):
        """Test handling restore completion with expiry time."""
        # Arrange
        bucket = "test-bucket"
        key = "documents/case123/report.pdf"
        restore_expiry = "2025-12-31T23:59:59Z"

        # Act
        result = restore_event_processor.handle_restore_file(bucket, key, restore_expiry)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "File restore processed successfully"
        assert response_body["s3key"] == key
        assert response_body["restore_expiry"] == restore_expiry

        # Verify update_item was called with correct parameters
        mock_table.update_item.assert_called_once()
        call_args = mock_table.update_item.call_args[1]
        assert call_args["Key"] == {"document_id": "report"}
        assert "UpdateExpression" in call_args
        # Check that restore_status value is set
        assert any("restored" == v for v in call_args["ExpressionAttributeValues"].values())

    def test_handle_restore_file_without_expiry(self, mock_table):
        """Test handling restore completion without expiry time."""
        # Arrange
        bucket = "test-bucket"
        key = "documents/test.pdf"

        # Act
        result = restore_event_processor.handle_restore_file(bucket, key, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "File restore processed successfully"
        assert response_body["restore_expiry"] is None

        # Verify DynamoDB was updated
        mock_table.update_item.assert_called_once()
        call_args = mock_table.update_item.call_args[1]
        assert call_args["Key"] == {"document_id": "test"}

    def test_handle_restore_file_with_path(self, mock_table):
        """Test handling restore for file with nested path."""
        # Arrange
        bucket = "test-bucket"
        key = "2025/01/15/document.pdf"
        restore_expiry = "2025-02-15T00:00:00Z"

        # Act
        result = restore_event_processor.handle_restore_file(bucket, key, restore_expiry)

        # Assert
        assert result["statusCode"] == 200

        # Verify document_id was extracted correctly
        call_args = mock_table.update_item.call_args[1]
        assert call_args["Key"] == {"document_id": "document"}

    def test_handle_restore_file_dynamodb_error(self, mock_table):
        """Test error handling when DynamoDB update fails."""
        # Arrange
        bucket = "test-bucket"
        key = "documents/test.pdf"
        mock_table.update_item.side_effect = Exception("DynamoDB error")

        # Act & Assert
        with pytest.raises(Exception, match="DynamoDB error"):
            restore_event_processor.handle_restore_file(bucket, key, None)


class TestLambdaHandler:
    """Tests for lambda_handler function."""

    def test_lambda_handler_restore_completed(self, mock_environment, sample_restore_event):
        """Test lambda_handler with Object Restore Completed event."""
        with patch.object(restore_event_processor, "handle_restore_file") as mock_handle:
            mock_handle.return_value = {
                "statusCode": 200,
                "body": json.dumps({"message": "success"}),
            }

            # Act
            result = restore_event_processor.lambda_handler(sample_restore_event, None)

            # Assert
            assert result == {"statusCode": 200, "body": json.dumps({"message": "success"})}
            mock_handle.assert_called_once_with(
                "test-bucket", "documents/test-file.pdf", "2025-12-31T23:59:59Z"
            )

    def test_lambda_handler_restore_no_expiry(
        self, mock_environment, sample_restore_event_no_expiry
    ):
        """Test lambda_handler without restore expiry time."""
        with patch.object(restore_event_processor, "handle_restore_file") as mock_handle:
            mock_handle.return_value = {
                "statusCode": 200,
                "body": json.dumps({"message": "success"}),
            }

            # Act
            restore_event_processor.lambda_handler(sample_restore_event_no_expiry, None)

            # Assert
            mock_handle.assert_called_once_with("test-bucket", "documents/test-file.pdf", None)

    def test_lambda_handler_folder_event(self, mock_environment):
        """Test lambda_handler ignores folder events."""
        # Arrange
        folder_event = {
            "detail-type": "Object Restore Completed",
            "detail": {"bucket": {"name": "test-bucket"}, "object": {"key": "documents/folder/"}},
        }

        # Act
        result = restore_event_processor.lambda_handler(folder_event, None)

        # Assert
        assert result == {"statusCode": 200, "body": "Folder event ignored"}

    def test_lambda_handler_unknown_event_type(self, mock_environment):
        """Test lambda_handler with unknown event type."""
        # Arrange
        unknown_event = {
            "detail-type": "Unknown Event Type",
            "detail": {"bucket": {"name": "test-bucket"}, "object": {"key": "documents/test.pdf"}},
        }

        # Act
        result = restore_event_processor.lambda_handler(unknown_event, None)

        # Assert
        assert result == {"statusCode": 200, "body": "Unknown event type"}

    def test_lambda_handler_missing_detail(self, mock_environment):
        """Test lambda_handler with malformed event."""
        # Arrange
        bad_event = {"some": "data"}

        # Act
        result = restore_event_processor.lambda_handler(bad_event, None)

        # Assert
        assert result["statusCode"] == 500
        response_body = json.loads(result["body"])
        assert "error" in response_body

    def test_lambda_handler_exception_in_handler(self, mock_environment, sample_restore_event):
        """Test lambda_handler when handle_restore_file raises exception."""
        with patch.object(restore_event_processor, "handle_restore_file") as mock_handle:
            mock_handle.side_effect = Exception("Processing error")

            # Act
            result = restore_event_processor.lambda_handler(sample_restore_event, None)

            # Assert
            assert result["statusCode"] == 500
            response_body = json.loads(result["body"])
            assert "error" in response_body


# Integration-style tests
class TestRestoreEventProcessorIntegration:
    """Integration tests for restore event processor."""

    def test_full_restore_workflow(self, mock_environment, mock_table, sample_restore_event):
        """Test complete restore workflow."""
        # Act
        result = restore_event_processor.lambda_handler(sample_restore_event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "File restore processed successfully"
        assert response_body["s3key"] == "documents/test-file.pdf"
        assert response_body["restore_expiry"] == "2025-12-31T23:59:59Z"

        # Verify DynamoDB was updated correctly
        mock_table.update_item.assert_called_once()
        call_args = mock_table.update_item.call_args[1]
        assert call_args["Key"] == {"document_id": "test-file"}
        # Check that the values are present (keys may vary due to ExpressionAttributeNames)
        assert any("restored" == v for v in call_args["ExpressionAttributeValues"].values())
        assert any(
            "2025-12-31T23:59:59Z" == v for v in call_args["ExpressionAttributeValues"].values()
        )

    def test_multiple_files_restore(self, mock_environment, mock_table):
        """Test restoring multiple files."""
        files = ["documents/file1.pdf", "documents/file2.pdf", "documents/file3.pdf"]

        for file_key in files:
            event = {
                "detail-type": "Object Restore Completed",
                "detail": {
                    "bucket": {"name": "test-bucket"},
                    "object": {"key": file_key},
                    "restore-expiry-time": "2025-12-31T23:59:59Z",
                },
            }

            # Act
            result = restore_event_processor.lambda_handler(event, None)

            # Assert
            assert result["statusCode"] == 200

        # Verify all files were processed
        assert mock_table.update_item.call_count == 3


if __name__ == "__main__":
    pytest.main([__file__])
