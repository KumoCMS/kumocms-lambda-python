import base64
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
os.environ["S3_BUCKET"] = "test-s3-bucket"
os.environ["DOCUMENTS_TABLE"] = "test-documents-table"

# Add the src/handlers/api and src/common directories to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "handlers" / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "common"))

import replace


@pytest.fixture
def mock_s3():
    """Mock S3 client."""
    with patch.object(replace, "s3") as mock_s3_client:
        yield mock_s3_client


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource."""
    with patch.object(replace, "dynamodb") as mock_db:
        mock_table = Mock()
        mock_db.Table.return_value = mock_table
        yield mock_table


@pytest.fixture
def sample_file_content():
    """Sample file content for testing."""
    return b"This is a test PDF file content"


@pytest.fixture
def sample_replace_event(sample_file_content):
    """Sample API Gateway event for document replacement."""
    encoded_content = base64.b64encode(sample_file_content).decode("utf-8")
    return {
        "pathParameters": {"id": "test-doc-id-123"},
        "body": json.dumps(
            {
                "file_content": encoded_content,
                "file_name": "updated-document.pdf",
                "content_type": "application/pdf",
                "meta_json": {"description": "Updated file", "author": "Tester"},
            }
        ),
        "headers": {"Content-Type": "application/json"},
    }


class TestReplaceHandler:
    """Tests for replace lambda_handler function."""

    def test_successful_replace_exists(
        self, mock_s3, mock_dynamodb, sample_replace_event, sample_file_content
    ):
        """Test successful document replacement when it already exists."""
        # Arrange
        mock_s3.put_object.return_value = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "ETag": '"abc123"',
        }

        # Act
        result = replace.lambda_handler(sample_replace_event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["message"] == "File replaced successfully"
        assert response_body["document_id"] == "test-doc-id-123"

        # Verify S3 put_object was called for both meta and file
        # The keys should be based on the ID from path
        calls = mock_s3.put_object.call_args_list
        assert any(c[1]["Key"] == "test-doc-id-123.pdf" for c in calls)
        assert any(c[1]["Key"] == "test-doc-id-123.meta.json" for c in calls)

        # Verify DynamoDB put_item was called
        mock_dynamodb.put_item.assert_called_once()
        args, kwargs = mock_dynamodb.put_item.call_args
        assert kwargs["Item"]["document_id"] == "test-doc-id-123"
        assert kwargs["Item"]["file_name"] == "updated-document.pdf"

    def test_replace_presigned_url(self, mock_s3, mock_dynamodb):
        """Test replacement with presigned URL for large file."""
        # Arrange
        event = {
            "pathParameters": {"id": "large-doc-id"},
            "body": json.dumps(
                {
                    "file_name": "large.pdf",
                    "file_size": 20 * 1024 * 1024,  # 20MB
                    "meta_json": {"key": "value"},
                }
            ),
        }
        mock_s3.generate_presigned_url.return_value = "https://presigned-url.com"

        # Act
        result = replace.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["method"] == "presigned_url"
        assert response_body["upload_url"] == "https://presigned-url.com"

        # Verify DynamoDB still called to update metadata
        mock_dynamodb.put_item.assert_called_once()

    def test_missing_id_in_path(self, mock_s3, mock_dynamodb):
        """Test failure when ID is missing in path."""
        # Arrange
        event = {"body": json.dumps({"file_name": "test.pdf"})}

        # Act
        result = replace.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        assert "Document ID is required" in json.loads(result["body"])["error"]

    def test_missing_meta_json(self, mock_s3, mock_dynamodb):
        """Test failure when meta_json is missing."""
        # Arrange
        event = {
            "pathParameters": {"id": "some-id"},
            "body": json.dumps({"file_name": "test.pdf", "file_content": "base64content"}),
        }

        # Act
        result = replace.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 400
        assert "meta.json file required" in json.loads(result["body"])["error"]


if __name__ == "__main__":
    pytest.main([__file__])
