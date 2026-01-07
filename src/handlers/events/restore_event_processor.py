import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

import boto3

# Add common directory to path to import common
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../common")))
try:
    from common import create_or_update_record, extract_file_id  # type: ignore
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

# Initialize the DynamoDB table
table = dynamodb.Table(DOCUMENTS_TABLE)


def handle_restore_file(bucket: str, key: str, restore_expiry: str | None = None) -> dict[str, Any]:
    """Handle S3 object restore completion events.

    Updates the document record in DynamoDB with restore status and expiry.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.
        restore_expiry: Optional timestamp when the restored object will expire.

    Returns:
        Response dictionary.
    """
    logger.info(f"Handling file restore for key: {key}")

    try:
        # Extract document_id from s3key
        document_id = extract_file_id(key)

        # Update existing record
        update_data = {
            "s3key": key,
            "restore_status": "restored",
            "updateddatetime": datetime.now(UTC).isoformat(),
        }

        # Add restore expiry if provided from the event
        if restore_expiry:
            update_data["restore_expiry"] = restore_expiry
            logger.info(f"Setting restore_expiry to: {restore_expiry}")

        create_or_update_record(table, document_id, update_data, is_update=True)
        logger.info(f"Successfully updated DynamoDB record for {document_id}")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "File restore processed successfully",
                    "s3key": key,
                    "restore_expiry": restore_expiry,
                }
            ),
        }

    except Exception as e:
        logger.error(f"Error processing restore for {key} in {bucket}: {e}")
        raise e


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process S3 object restore events.

    Args:
        event: S3 EventBridge event.
        context: Lambda context object.

    Returns:
        Lambda response object.
    """
    try:
        # Parse EventBridge event
        detail = event.get("detail", {})
        bucket = detail.get("bucket", {}).get("name")
        key = detail.get("object", {}).get("key")
        detail_type = event.get("detail-type")

        if not bucket or not key or not detail_type:
            logger.error(f"Malformed event: {event}")
            raise ValueError("Missing mandatory fields: bucket, key, or detail-type")

        # Skip folder creation events
        if key and key.endswith("/"):
            return {"statusCode": 200, "body": "Folder event ignored"}

        if detail_type == "Object Restore Completed":
            # Extract restore expiry time from event
            restore_expiry = detail.get("restore-expiry-time")
            return handle_restore_file(bucket, key, restore_expiry)
        else:
            logger.warning(f"Unknown event detail-type: {detail_type}")
            return {"statusCode": 200, "body": "Unknown event type"}

    except Exception as e:
        logger.exception(f"Error processing restore event: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Internal server error", "error": str(e)}),
        }
