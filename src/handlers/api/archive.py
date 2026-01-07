import json
import logging
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import unquote

import boto3

# Add common directory to path to import common
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../common")))
try:
    # Check if common exists
    from common import retry_with_backoff  # type: ignore # noqa: F401
except ImportError:
    # Use logger if initialized, otherwise print
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
        body: Response body (will be JSON serialized).

    Returns:
        Formatted response dictionary for API Gateway.
    """
    return {
        "statusCode": status_code,
        "headers": COMMON_HEADERS,
        "body": json.dumps(body, default=decimal_default),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle document archive requests.

    Moves a document to GLACIER storage class and updates DynamoDB.

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

        # URL decode the document ID
        if document_id:
            document_id = unquote(document_id)

        if not document_id:
            return create_response(
                400, {"error": "Bad Request", "message": "Document ID is required"}
            )

        # Get document metadata from DynamoDB
        table = dynamodb.Table(DOCUMENTS_TABLE)

        try:
            response = table.get_item(Key={"document_id": document_id})
            document = response.get("Item")

            if not document:
                return create_response(
                    404,
                    {
                        "error": "Document not found",
                        "message": f"Document with ID {document_id} does not exist",
                    },
                )
        except Exception as e:
            logger.error(f"Error retrieving document metadata for {document_id}: {e}")
            return create_response(
                500, {"error": "Database error", "message": "Failed to retrieve metadata"}
            )

        # Check if document is already archived
        current_storage_class = document.get("storage_class", "STANDARD")
        if current_storage_class in ["GLACIER", "DEEP_ARCHIVE"]:
            return create_response(
                409,
                {
                    "error": "Document already archived",
                    "message": (f"Document already in {str(current_storage_class)} storage class"),
                    "storage_class": current_storage_class,
                },
            )

        # Get the s3key from the document
        s3key = document.get("s3key", document_id)

        # Archive the document by changing storage class to GLACIER
        try:
            raw_meta = document.get("metadata")
            metadata: dict[str, str] = (
                {str(k): str(v) for k, v in raw_meta.items()} if isinstance(raw_meta, dict) else {}
            )
            s3.copy_object(
                Bucket=S3_BUCKET,
                CopySource={"Bucket": S3_BUCKET, "Key": s3key},
                Key=s3key,
                StorageClass="GLACIER",
                MetadataDirective="REPLACE",
                Metadata=metadata,
            )
            logger.info(f"Successfully moved {s3key} to Glacier storage")
        except Exception as e:
            logger.error(f"Error archiving document {document_id} to Glacier: {e}")
            return create_response(
                500,
                {
                    "error": "Archive failed",
                    "message": "Failed to move document to archive storage",
                },
            )

        # Update document status in DynamoDB
        now = datetime.now(UTC).isoformat()
        try:
            table.update_item(
                Key={"document_id": document_id},
                UpdateExpression=(
                    "SET storage_class = :sc, archived_date = :ad, updateddatetime = :ud"
                ),
                ExpressionAttributeValues={":sc": "GLACIER", ":ad": now, ":ud": now},
            )
            logger.info(
                f"Updated DynamoDB record for document_id {document_id} with archive status"
            )
        except Exception as e:
            logger.error(f"Error updating document status in DynamoDB for {document_id}: {e}")
            # Non-fatal error as S3 is already updated, but record is out of sync

        return create_response(
            200,
            {
                "message": "Document archived successfully",
                "document_id": document_id,
                "storage_class": "GLACIER",
                "archived_date": now,
                "file_name": document.get("file_name"),
                "size": document.get("size"),
            },
        )

    except Exception as e:
        logger.exception(f"Archive error: {str(e)}")
        return create_response(
            500, {"error": "Internal server error", "message": "Archive operation failed"}
        )
