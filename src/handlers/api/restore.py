import json
import logging
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

import boto3
from botocore.exceptions import ClientError

# Add common directory to path to import common
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../common")))
try:
    # Check if common exists
    from common import retry_with_backoff  # type: ignore # noqa: F401
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("Could not import common utilities")

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

# Environment variables
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")

# Common headers for API responses
COMMON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def decimal_default(obj: Any) -> int | float:
    """JSON serializer for DynamoDB Decimal types.

    Args:
        obj: The object to serialize.

    Returns:
        Int or float representation of the Decimal.

    Raises:
        TypeError: If the object is not a Decimal.
    """
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def create_response(status_code: int, body: Any) -> dict[str, Any]:
    """Create a standardized API Gateway response.

    Args:
        status_code: HTTP status code.
        body: Response body.

    Returns:
        Formatted response dictionary for API Gateway.
    """
    return {
        "statusCode": status_code,
        "headers": COMMON_HEADERS,
        "body": json.dumps(body, default=decimal_default),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle document restore requests.

    Initiates S3 Glacier restore and updates DynamoDB status.

    Args:
        event: API Gateway event dictionary.
        context: Lambda context object.

    Returns:
        API Gateway response dictionary.
    """
    try:
        # Extract document ID from path parameters
        path_parameters = event.get("pathParameters", {})
        document_id = path_parameters.get("id")

        if document_id:
            document_id = unquote(document_id)

        # Parse request body for restore options
        try:
            body = json.loads(event.get("body", "{}"))
        except json.JSONDecodeError:
            return create_response(
                400, {"error": "Invalid JSON", "message": "Request body must be valid JSON"}
            )

        restore_days = body.get("days", 1)  # Default to 1 day
        restore_tier = body.get("tier", "Standard")  # Standard, Expedited, or Bulk

        if not document_id:
            return create_response(400, {"error": "Bad Request", "message": "Document ID required"})

        # Validate restore parameters
        if not (1 <= restore_days <= 365):
            return create_response(
                400, {"error": "Invalid restore days", "message": "Must be between 1 and 365"}
            )

        if restore_tier not in ["Standard", "Expedited", "Bulk"]:
            return create_response(
                400,
                {
                    "error": "Invalid restore tier",
                    "message": "Must be Standard, Expedited, or Bulk",
                },
            )

        # Get document metadata from DynamoDB
        table = dynamodb.Table(DOCUMENTS_TABLE)
        try:
            response = table.get_item(Key={"document_id": document_id})
            document = response.get("Item")

            if not document:
                return create_response(404, {"error": "Not Found", "message": "Document not found"})
        except Exception as e:
            logger.error(f"Error retrieving metadata for {document_id}: {e}")
            return create_response(
                500, {"error": "Database error", "message": "Failed to retrieve metadata"}
            )

        # Check if document is archived
        current_storage_class = document.get("storage_class", "STANDARD")
        if current_storage_class not in ["GLACIER", "DEEP_ARCHIVE"]:
            return create_response(
                409,
                {
                    "error": "Document not archived",
                    "message": (
                        f"Document is in {str(current_storage_class)!r} class, no restore needed"
                    ),
                },
            )

        # Check if already in progress
        if document.get("restore_status") == "in_progress":
            return create_response(
                409, {"error": "Restore in progress", "message": "Restore already in progress"}
            )

        # Get S3 key
        s3key = document.get("s3key", document_id)

        # Initiate restore
        try:
            s3.restore_object(
                Bucket=S3_BUCKET,
                Key=str(s3key),
                RestoreRequest={
                    "Days": restore_days,
                    "GlacierJobParameters": {"Tier": restore_tier},
                },
            )
            logger.info(f"Initiated {restore_tier} restore for {str(s3key)!r}")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "RestoreAlreadyInProgress" or "RestoreAlreadyInProgress" in str(e):
                return create_response(
                    409,
                    {
                        "error": "Restore already in progress",
                        "message": "S3 restore already in progress",
                    },
                )
            logger.error(f"S3 restore error for {document_id}: {e}")
            return create_response(500, {"error": "Restore failed", "message": str(e)})

        # Update DynamoDB
        now = datetime.now(UTC).isoformat()
        try:
            table.update_item(
                Key={"document_id": document_id},
                UpdateExpression=(
                    "SET restore_status = :rs, restore_initiated_date = :rd, "
                    "restore_days = :days, restore_tier = :tier, updateddatetime = :ud"
                ),
                ExpressionAttributeValues={
                    ":rs": "in_progress",
                    ":rd": now,
                    ":days": restore_days,
                    ":tier": restore_tier,
                    ":ud": now,
                },
            )
            logger.info(f"Updated DynamoDB restore status for {document_id}")
        except Exception as e:
            logger.error(f"Error updating DynamoDB for {document_id}: {e}")

        completion_estimates = {
            "Expedited": "1-5 minutes",
            "Standard": "3-5 hours",
            "Bulk": "5-12 hours",
        }

        return create_response(
            200,
            {
                "message": "Document restore initiated successfully",
                "document_id": document_id,
                "restore_tier": restore_tier,
                "restore_days": restore_days,
                "restore_status": "in_progress",
                "estimated_completion": completion_estimates.get(restore_tier, "Unknown"),
                "initiated_date": now,
                "file_name": document.get("file_name"),
                "size": document.get("size"),
            },
        )

    except Exception as e:
        if "RestoreAlreadyInProgress" in str(e):
            return create_response(409, {"error": "Restore already in progress", "message": str(e)})
        logger.exception(f"Restore error: {str(e)}")
        message = f"Restore failed: {str(e)}"
        return create_response(500, {"error": "Internal server error", "message": message})
