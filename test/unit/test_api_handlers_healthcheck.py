import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Set AWS environment variables
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["DOCUMENTS_TABLE"] = "test-documents-table"
os.environ["S3_BUCKET"] = "test-s3-bucket"

# Add the src/handlers/api and src/common directories to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "handlers" / "api"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "common"))

import healthcheck


@pytest.fixture
def mock_s3():
    """Mock S3 client."""
    with patch.object(healthcheck, "s3") as mock_s3_client:
        yield mock_s3_client


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource."""
    with patch.object(healthcheck, "dynamodb") as mock_db:
        mock_table = MagicMock()
        mock_db.Table.return_value = mock_table
        yield mock_db, mock_table


class TestHealthcheckHandler:
    """Tests for healthcheck lambda_handler function."""

    def test_healthcheck_success(self, mock_s3, mock_dynamodb):
        """Test healthcheck when all services are healthy."""
        # Arrange
        mock_db, mock_table = mock_dynamodb
        event = {}
        mock_s3.head_bucket.return_value = {}
        mock_table.scan.return_value = {"Items": []}

        # Act
        result = healthcheck.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["status"] == "healthy"
        assert response_body["checks"]["s3"]["status"] == "healthy"
        assert response_body["checks"]["dynamodb"]["status"] == "healthy"

        mock_s3.head_bucket.assert_called_once_with(Bucket="test-s3-bucket")
        mock_db.Table.assert_called_once_with("test-documents-table")
        mock_table.scan.assert_called_once_with(Limit=1)

    def test_healthcheck_s3_unhealthy(self, mock_s3, mock_dynamodb):
        """Test healthcheck when S3 is unhealthy."""
        # Arrange
        mock_db, mock_table = mock_dynamodb
        event = {}
        mock_s3.head_bucket.side_effect = Exception("S3 error")
        mock_table.scan.return_value = {"Items": []}

        # Act
        result = healthcheck.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 503
        response_body = json.loads(result["body"])
        assert response_body["status"] == "unhealthy"
        assert response_body["checks"]["s3"]["status"] == "unhealthy"
        assert "S3 error" in response_body["checks"]["s3"]["error"]
        assert response_body["checks"]["dynamodb"]["status"] == "healthy"

    def test_healthcheck_dynamodb_unhealthy(self, mock_s3, mock_dynamodb):
        """Test healthcheck when DynamoDB is unhealthy."""
        # Arrange
        mock_db, mock_table = mock_dynamodb
        event = {}
        mock_s3.head_bucket.return_value = {}
        mock_table.scan.side_effect = Exception("DynamoDB error")

        # Act
        result = healthcheck.lambda_handler(event, None)

        # Assert
        assert result["statusCode"] == 503
        response_body = json.loads(result["body"])
        assert response_body["status"] == "unhealthy"
        assert response_body["checks"]["dynamodb"]["status"] == "unhealthy"
        assert "DynamoDB error" in response_body["checks"]["dynamodb"]["error"]
        assert response_body["checks"]["s3"]["status"] == "healthy"

    def test_healthcheck_missing_env_vars(self):
        """Test healthcheck when environment variables are missing."""
        with patch.dict(os.environ, {}, clear=True):
            # We need to reload or re-patch the handler's globals
            with patch("healthcheck.S3_BUCKET", None), patch("healthcheck.DOCUMENTS_TABLE", None):
                result = healthcheck.lambda_handler({}, None)

                assert result["statusCode"] == 503
                response_body = json.loads(result["body"])
                assert response_body["status"] == "unhealthy"
                assert "environment variable not set" in response_body["checks"]["s3"]["error"]
                assert (
                    "environment variable not set" in response_body["checks"]["dynamodb"]["error"]
                )


if __name__ == "__main__":
    pytest.main([__file__])
