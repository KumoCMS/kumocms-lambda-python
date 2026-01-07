import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError

# Set AWS environment variables BEFORE importing any modules that use boto3
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["DOCUMENTS_TABLE"] = "test-documents-table"
os.environ["S3_BUCKET"] = "test-s3-bucket"

# Add the src/handlers/events and src/common directories to the Python path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "handlers" / "events"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "common"))

import event_processor

import common


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
    original_table = event_processor.table
    event_processor.table = mock_table
    yield mock_table
    # Restore original table after test
    event_processor.table = original_table


@pytest.fixture
def mock_s3():
    """Mock S3 client."""
    with patch.object(event_processor, "s3") as mock_s3_client:
        yield mock_s3_client


@pytest.fixture
def sample_event():
    """Sample EventBridge event for testing."""
    return {
        "detail": {"bucket": {"name": "test-bucket"}, "object": {"key": "documents/test-file.pdf"}}
    }


@pytest.fixture
def sample_meta_event():
    """Sample EventBridge event for meta.json file."""
    return {
        "detail": {
            "bucket": {"name": "test-bucket"},
            "object": {"key": "documents/test-file.pdf.meta.json"},
        }
    }


class TestGetExistingRecord:
    """Tests for get_existing_record function."""

    def test_get_existing_record_found(self, mock_table):
        """Test when record exists."""
        # Arrange
        expected_item = {"document_id": "test-file", "metadata_field": "value"}
        mock_table.get_item.return_value = {"Item": expected_item}

        # Act
        result = event_processor.get_existing_record(mock_table, "test-file")

        # Assert
        assert result == expected_item
        mock_table.get_item.assert_called_once_with(Key={"document_id": "test-file"})

    def test_get_existing_record_not_found(self, mock_table):
        """Test when record doesn't exist."""
        # Arrange
        mock_table.get_item.return_value = {}

        # Act
        result = event_processor.get_existing_record(mock_table, "test-file")

        # Assert
        assert result is None
        mock_table.get_item.assert_called_once_with(Key={"document_id": "test-file"})

    def test_get_existing_record_exception(self, mock_table):
        """Test when get_item raises an exception."""
        # Arrange
        mock_table.get_item.side_effect = Exception("DynamoDB error")

        # Act
        result = event_processor.get_existing_record(mock_table, "test-file")

        # Assert
        assert result is None


class TestCreateOrUpdateRecord:
    """Tests for create_or_update_record function."""

    def test_create_new_record(self, mock_table):
        """Test creating a new record."""
        # Arrange
        record_data = {"file_name": "test.pdf", "size": 1024}

        # Act
        common.create_or_update_record(mock_table, "test-file", record_data, is_update=False)

        # Assert
        mock_table.put_item.assert_called_once()
        call_args = mock_table.put_item.call_args[1]
        assert call_args["Item"] == {
            "document_id": "test-file",
            "file_name": "test.pdf",
            "size": 1024,
        }
        assert "ConditionExpression" in call_args

    def test_update_existing_record(self, mock_table):
        """Test updating an existing record."""
        # Arrange
        record_data = {"file_name": "test.pdf", "size": 1024}

        # Act
        common.create_or_update_record(mock_table, "test-file", record_data, is_update=True)

        # Assert
        mock_table.update_item.assert_called_once()
        call_args = mock_table.update_item.call_args[1]
        assert call_args["Key"] == {"document_id": "test-file"}
        assert "SET" in call_args["UpdateExpression"]

    def test_update_with_reserved_words(self, mock_table):
        """Test updating with DynamoDB reserved words."""
        # Arrange
        record_data = {"key": "value", "timestamp": "2025-01-01", "status": "active"}

        # Act
        common.create_or_update_record(mock_table, "test-file", record_data, is_update=True)

        # Assert
        mock_table.update_item.assert_called_once()
        call_args = mock_table.update_item.call_args[1]
        assert "ExpressionAttributeNames" in call_args


class TestHandleRegularFile:
    """Tests for handle_regular_file function."""

    def test_handle_regular_file_new_record(self, mock_table, mock_s3):
        """Test handling a new regular file upload."""
        # Arrange
        mock_s3.get_object.return_value = {
            "ContentType": "application/pdf",
            "ContentLength": 1024,
            "ETag": '"abcd1234"',
        }
        mock_table.get_item.return_value = {}  # No existing record

        # Act
        result = event_processor.handle_regular_file("test-bucket", "documents/test.pdf")

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "File processed successfully"
        assert response_body["s3key"] == "documents/test.pdf"
        assert response_body["etag"] == "abcd1234"

        mock_s3.get_object.assert_called_once_with(Bucket="test-bucket", Key="documents/test.pdf")
        mock_table.put_item.assert_called_once()

    def test_handle_regular_file_update_existing(self, mock_table, mock_s3):
        """Test handling a regular file when meta.json was uploaded first."""
        # Arrange
        mock_s3.get_object.return_value = {
            "ContentType": "application/pdf",
            "ContentLength": 1024,
            "ETag": '"abcd1234"',
        }
        existing_record = {"s3key": "documents/test.pdf", "metadata_field": "value"}
        mock_table.get_item.return_value = {"Item": existing_record}

        # Act
        result = event_processor.handle_regular_file("test-bucket", "documents/test.pdf")

        # Assert
        assert result["statusCode"] == 200
        mock_table.update_item.assert_called_once()

    def test_handle_regular_file_s3_error(self, mock_table, mock_s3):
        """Test handling S3 error."""
        # Arrange
        mock_s3.get_object.side_effect = Exception("S3 error")

        # Act & Assert
        with pytest.raises(Exception, match="S3 error"):
            event_processor.handle_regular_file("test-bucket", "documents/test.pdf")


class TestHandleMetaJsonFile:
    """Tests for handle_meta_json_file function."""

    def test_handle_meta_json_new_record(self, mock_table, mock_s3):
        """Test handling meta.json for a new file."""
        # Arrange
        meta_content = json.dumps({"document_type": "invoice", "other_field": "value"})
        mock_s3.get_object.return_value = {
            "Body": Mock(read=Mock(return_value=meta_content.encode("utf-8"))),
            "ETag": '"meta1234"',
        }
        mock_table.get_item.return_value = {}  # No existing record

        # Act
        result = event_processor.handle_meta_json_file(
            "test-bucket", "documents/test.pdf.meta.json"
        )

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["document_id"] == "test"

        assert response_body["deleted_from_s3"] is False

        mock_table.put_item.assert_called_once()
        # Meta.json files are no longer deleted
        mock_s3.delete_object.assert_not_called()

    def test_handle_meta_json_update_existing(self, mock_table, mock_s3):
        """Test handling meta.json when file record already exists."""
        # Arrange
        meta_content = json.dumps({"document_type": "invoice"})
        mock_s3.get_object.return_value = {
            "Body": Mock(read=Mock(return_value=meta_content.encode("utf-8"))),
            "ETag": '"meta1234"',
        }
        existing_record = {
            "document_id": "test",
            "s3key": "documents/test.pdf",
            "file_name": "test.pdf",
        }
        mock_table.get_item.return_value = {"Item": existing_record}

        # Act
        result = event_processor.handle_meta_json_file(
            "test-bucket", "documents/test.pdf.meta.json"
        )

        # Assert
        assert result["statusCode"] == 200
        mock_table.update_item.assert_called_once()
        # Meta.json files are no longer deleted
        mock_s3.delete_object.assert_not_called()

    def test_handle_meta_json_minimal_metadata(self, mock_table, mock_s3):
        """Test handling meta.json with minimal metadata (should still succeed)."""
        # Arrange
        meta_content = json.dumps({"other_field": "value"})
        mock_s3.get_object.return_value = {
            "Body": Mock(read=Mock(return_value=meta_content.encode("utf-8"))),
            "ETag": '"meta1234"',
        }
        mock_table.get_item.return_value = {}  # No existing record

        # Act
        result = event_processor.handle_meta_json_file(
            "test-bucket", "documents/test.pdf.meta.json"
        )

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["document_id"] == "test"
        assert response_body["deleted_from_s3"] is False
        mock_table.put_item.assert_called_once()
        # Meta.json files are no longer deleted
        mock_s3.delete_object.assert_not_called()

    def test_handle_meta_json_not_deleted(self, mock_table, mock_s3):
        """Test that meta.json files are no longer deleted from S3."""
        # Arrange
        meta_content = json.dumps({"document_type": "invoice"})
        mock_s3.get_object.return_value = {
            "Body": Mock(read=Mock(return_value=meta_content.encode("utf-8"))),
            "ETag": '"meta1234"',
        }
        mock_table.get_item.return_value = {}

        # Act
        result = event_processor.handle_meta_json_file(
            "test-bucket", "documents/test.pdf.meta.json"
        )

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["document_id"] == "test"
        assert response_body["deleted_from_s3"] is False
        # Verify delete was not called
        mock_s3.delete_object.assert_not_called()


class TestLambdaHandler:
    """Tests for lambda_handler function."""

    def test_lambda_handler_regular_file(self, mock_environment, sample_event):
        """Test lambda_handler with regular file."""
        with patch.object(event_processor, "handle_regular_file") as mock_handle:
            mock_handle.return_value = {"statusCode": 200, "body": "success"}

            # Act
            result = event_processor.lambda_handler(sample_event, None)

            # Assert
            assert result == {"statusCode": 200, "body": "success"}
            mock_handle.assert_called_once_with("test-bucket", "documents/test-file.pdf")

    def test_lambda_handler_meta_json_file(self, mock_environment, sample_meta_event):
        """Test lambda_handler with meta.json file."""
        with patch.object(event_processor, "handle_meta_json_file") as mock_handle:
            mock_handle.return_value = {"statusCode": 200, "body": "success"}

            # Act
            result = event_processor.lambda_handler(sample_meta_event, None)

            # Assert
            assert result == {"statusCode": 200, "body": "success"}
            mock_handle.assert_called_once_with("test-bucket", "documents/test-file.pdf.meta.json")

    def test_lambda_handler_folder_event(self, mock_environment):
        """Test lambda_handler with folder creation event."""
        # Arrange
        folder_event = {
            "detail": {"bucket": {"name": "test-bucket"}, "object": {"key": "documents/folder/"}}
        }

        # Act
        result = event_processor.lambda_handler(folder_event, None)

        # Assert
        assert result == {"statusCode": 200, "body": "Folder event ignored"}


# Integration-style tests
class TestEventProcessorIntegration:
    """Integration tests that test multiple components together."""

    def test_full_workflow_regular_file_first(self, mock_environment, mock_table, mock_s3):
        """Test complete workflow when regular file is uploaded first."""
        # Arrange
        mock_s3.get_object.return_value = {
            "ContentType": "application/pdf",
            "ContentLength": 1024,
            "ETag": '"abcd1234"',
        }
        mock_table.get_item.return_value = {}  # No existing record

        event = {
            "detail": {
                "bucket": {"name": "test-bucket"},
                "object": {"key": "documents/case123/document.pdf"},
            }
        }

        # Act
        result = event_processor.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert "File processed successfully" in response_body["message"]
        mock_table.put_item.assert_called_once()

    def test_full_workflow_meta_json_first(self, mock_environment, mock_table, mock_s3):
        """Test complete workflow when meta.json is uploaded first."""
        # Arrange
        meta_content = json.dumps({"document_type": "invoice"})
        mock_s3.get_object.return_value = {
            "Body": Mock(read=Mock(return_value=meta_content.encode("utf-8"))),
            "ETag": '"meta1234"',
        }
        mock_table.get_item.return_value = {}  # No existing record

        event = {
            "detail": {
                "bucket": {"name": "test-bucket"},
                "object": {"key": "documents/case123/document.pdf.meta.json"},
            }
        }

        # Act
        result = event_processor.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["document_id"] == "document"

        mock_table.put_item.assert_called_once()
        # Meta.json files are no longer deleted
        mock_s3.delete_object.assert_not_called()


# Test cases for concurrent upload handling
class TestConcurrentUploads:
    """Tests for handling concurrent uploads of file and meta.json."""

    def test_handle_regular_file_race_condition(self, mock_table, mock_s3):
        """Test handling race condition when both file and meta.json are uploaded concurrently."""
        # Arrange
        mock_s3.get_object.return_value = {
            "ContentType": "application/pdf",
            "ContentLength": 1024,
            "ETag": '"abcd1234"',
        }

        # Simulate race condition: first get_item returns None,
        # but put_item fails with ConditionalCheckFailedException
        mock_table.get_item.side_effect = [
            {},  # First call returns no record
            {
                "Item": {
                    "document_id": "test",
                    "s3key": "documents/test.pdf",
                    "metadata_field": "value",
                }
            },  # Second call (in retry) returns existing record
        ]

        # Simulate ConditionalCheckFailedException on put_item
        error_response = {
            "Error": {"Code": "ConditionalCheckFailedException", "Message": "Item already exists"}
        }
        mock_table.put_item.side_effect = ClientError(error_response, "PutItem")

        # Act
        result = event_processor.handle_regular_file("test-bucket", "documents/test.pdf")

        # Assert
        assert result["statusCode"] == 200
        # Should have called update_item after detecting the race condition
        mock_table.update_item.assert_called_once()

    def test_handle_meta_json_race_condition(self, mock_table, mock_s3):
        """Test handling race condition when meta.json detects concurrent file upload."""
        # Arrange
        meta_content = json.dumps({"document_type": "invoice"})
        mock_s3.get_object.return_value = {
            "Body": Mock(read=Mock(return_value=meta_content.encode("utf-8"))),
            "ETag": '"meta1234"',
        }

        # Simulate race condition
        mock_table.get_item.side_effect = [
            {},  # First call returns no record
            {
                "Item": {"document_id": "test", "s3key": "documents/test.pdf", "size": 1024}
            },  # Second call (in retry) returns existing record
        ]

        # Simulate ConditionalCheckFailedException on put_item
        error_response = {
            "Error": {"Code": "ConditionalCheckFailedException", "Message": "Item already exists"}
        }
        mock_table.put_item.side_effect = ClientError(error_response, "PutItem")

        # Act
        result = event_processor.handle_meta_json_file(
            "test-bucket", "documents/test.pdf.meta.json"
        )

        # Assert
        assert result["statusCode"] == 200
        # Should have called update_item after detecting the race condition
        mock_table.update_item.assert_called_once()
        # Meta.json files are no longer deleted
        mock_s3.delete_object.assert_not_called()

    def test_conditional_expression_prevents_overwrite(self, mock_table):
        """Test that conditional expression properly prevents overwriting existing records."""
        # Arrange
        record_data = {"file_name": "test.pdf", "size": 1024}

        # Mock ConditionalCheckFailedException
        error_response = {
            "Error": {"Code": "ConditionalCheckFailedException", "Message": "Item already exists"}
        }
        mock_table.put_item.side_effect = ClientError(error_response, "PutItem")

        # Act & Assert
        with pytest.raises(ClientError) as exc_info:
            common.create_or_update_record(mock_table, "test-file", record_data, is_update=False)

        assert exc_info.value.response["Error"]["Code"] == "ConditionalCheckFailedException"
        # Verify ConditionExpression was used in put_item call
        call_args = mock_table.put_item.call_args
        assert "ConditionExpression" in call_args[1]


if __name__ == "__main__":
    pytest.main([__file__])
