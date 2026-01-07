import json
import logging
import os
import sys
from typing import Any

import boto3

# Add common directory to path if needed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../common")))

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

# Environment variables
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")

# Common headers
COMMON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Health check endpoint.

    Verifies connectivity and permissions to S3 and DynamoDB.

    Args:
        event: API Gateway event dictionary.
        context: Lambda context object.

    Returns:
        API Gateway response dictionary.
    """
    status = {
        "status": "healthy",
        "checks": {"s3": {"status": "unknown"}, "dynamodb": {"status": "unknown"}},
    }

    overall_healthy = True

    # Check S3
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET environment variable not set")

        # Try to head the bucket to check existence and permissions
        s3.head_bucket(Bucket=S3_BUCKET)
        s3_check: dict[str, Any] = status["checks"]["s3"]  # type: ignore
        s3_check["status"] = "healthy"
    except Exception as e:
        logger.error(f"S3 health check failed: {e}")
        status["checks"]["s3"] = {"status": "unhealthy", "error": str(e)}  # type: ignore
        overall_healthy = False

    # Check DynamoDB
    try:
        if not DOCUMENTS_TABLE:
            raise ValueError("DOCUMENTS_TABLE environment variable not set")

        # Scan with small limit to check existence and permissions
        table = dynamodb.Table(DOCUMENTS_TABLE)
        table.scan(Limit=1)
        db_check: dict[str, Any] = status["checks"]["dynamodb"]  # type: ignore
        db_check["status"] = "healthy"
    except Exception as e:
        logger.error(f"DynamoDB health check failed: {e}")
        status["checks"]["dynamodb"] = {"status": "unhealthy", "error": str(e)}  # type: ignore
        overall_healthy = False

    if not overall_healthy:
        status["status"] = "unhealthy"

    return {
        "statusCode": 200 if overall_healthy else 503,
        "headers": COMMON_HEADERS,
        "body": json.dumps(status),
    }
