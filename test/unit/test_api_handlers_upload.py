import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Set AWS environment variables BEFORE importing any modules that use boto3
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["S3_BUCKET"] = "test-s3-bucket"

# Add the src/handlers/api and src/common directories to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "handlers" / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "common"))

import upload


@pytest.fixture
def mock_s3():
    """Mock S3 client."""
    with patch.object(upload, "s3") as mock_s3_client:
        yield mock_s3_client


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource."""
    with patch.object(upload, "dynamodb") as mock_db:
        mock_table = Mock()
        mock_db.Table.return_value = mock_table
        yield mock_table


@pytest.fixture
def sample_file_content():
    """Sample file content for testing."""
    return b"This is a test PDF file content"


@pytest.fixture
def sample_upload_event():
    """Sample API Gateway event for file upload."""
    return {
        "body": json.dumps(
            {
                "file_name": "test-document.pdf",
                "file_size": 1024,
                "content_type": "application/pdf",
                "meta_json": {"description": "Test file", "author": "Tester"},
            }
        ),
        "headers": {"Content-Type": "application/json"},
    }


class TestUploadHandler:
    """Tests for upload lambda_handler function."""

    def test_successful_upload(self, mock_s3, mock_dynamodb, sample_upload_event):
        """Test successful pre-signed URL generation."""
        # Arrange
        mock_s3.generate_presigned_url.return_value = (
            "https://test-bucket.s3.amazonaws.com/upload-link"
        )
        mock_s3.put_object.return_value = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "ETag": '"abc123"',
        }

        # Act
        with patch("upload.datetime") as mock_datetime:
            mock_now = MagicMock()
            mock_datetime.now.return_value = mock_now
            result = upload.lambda_handler(sample_upload_event, None)

        # Assert
        assert result["statusCode"] == 200
        assert "Access-Control-Allow-Origin" in result["headers"]

        response_body = json.loads(result["body"])
        assert response_body["message"] == "Presigned URL generated"
        assert response_body["method"] == "presigned_url"
        assert "upload_url" in response_body
        assert "document_id" in response_body

        # Verify S3 put_object was called for meta.json
        mock_s3.put_object.assert_called_once()
        args, kwargs = mock_s3.put_object.call_args
        assert kwargs["Key"].endswith(".meta.json")

        # Verify S3 generate_presigned_url was called for the document
        mock_s3.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={
                "Bucket": "test-s3-bucket",
                "Key": f"{response_body['document_id']}.pdf",
                "ContentType": "application/pdf",
            },
            ExpiresIn=3600,
            HttpMethod="PUT",
        )

        # Verify DynamoDB put_item was called
        mock_dynamodb.put_item.assert_called_once()

    def test_upload_missing_meta_content(self, mock_s3, mock_dynamodb):
        """Test upload succeeds even with missing metadata."""
        # Arrange
        event = {"body": json.dumps({"file_name": "test.pdf"})}
        mock_s3.generate_presigned_url.return_value = "https://presigned-url"

        # Act
        result = upload.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert "document_id" in response_body
        assert response_body["message"] == "Presigned URL generated"

        # Verify S3 put_object was NOT called (no metadata to upload)
        mock_s3.put_object.assert_not_called()

        # Verify DynamoDB record has has_metadata="no"
        mock_dynamodb.put_item.assert_called_once()
        args, kwargs = mock_dynamodb.put_item.call_args
        assert kwargs["Item"]["has_metadata"] == "no"

    def test_upload_missing_file_name(self, mock_s3, mock_dynamodb):
        """Test upload with missing file name."""
        # Arrange
        event = {"body": json.dumps({"meta_json": {"key": "value"}})}

        # Act
        result = upload.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        response_body = json.loads(result["body"])
        assert "error" in response_body
        assert "name" in response_body["error"].lower()

        # Verify S3 was not called
        mock_s3.put_object.assert_not_called()
        mock_s3.generate_presigned_url.assert_not_called()

    def test_upload_default_content_type(self, mock_s3, mock_dynamodb):
        """Test upload with default content type."""
        # Arrange
        event = {
            "body": json.dumps(
                {
                    "file_name": "test-file.dat",
                    "meta_json": {"key": "value"},
                }
            )
        }

        mock_s3.generate_presigned_url.return_value = "https://presigned-url"
        mock_s3.put_object.return_value = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

        # Act
        result = upload.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200

        # Verify default content type was used in presigned URL Params
        mock_s3.generate_presigned_url.assert_called_once()
        args, kwargs = mock_s3.generate_presigned_url.call_args
        assert kwargs["Params"]["ContentType"] == "application/octet-stream"

        # Verify mocked dynamodb call
        mock_dynamodb.put_item.assert_called_once()

    def test_upload_s3_meta_failure(self, mock_s3, mock_dynamodb):
        """Test upload when S3 meta upload fails."""
        # Arrange
        event = {
            "body": json.dumps(
                {
                    "file_name": "test.pdf",
                    "meta_json": {"key": "value"},
                }
            )
        }

        mock_s3.put_object.side_effect = Exception("S3 error")

        # Act
        result = upload.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 500
        response_body = json.loads(result["body"])
        assert "error" in response_body

    def test_upload_empty_body(self, mock_s3, mock_dynamodb):
        """Test upload with empty request body."""
        # Arrange
        event = {}

        # Act
        result = upload.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        response_body = json.loads(result["body"])
        assert "error" in response_body

    def test_upload_cors_headers(self, mock_s3, mock_dynamodb, sample_upload_event):
        """Test that CORS headers are present in response."""
        # Arrange
        mock_s3.generate_presigned_url.return_value = "https://url"
        mock_s3.put_object.return_value = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

        # Act
        result = upload.lambda_handler(sample_upload_event, None)

        # Assert
        assert result["statusCode"] == 200
        headers = result["headers"]
        assert headers["Access-Control-Allow-Origin"] == "*"
        assert "Access-Control-Allow-Headers" in headers
        assert "Access-Control-Allow-Methods" in headers


if __name__ == "__main__":
    pytest.main([__file__])
