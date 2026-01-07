import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Add common directory to path to import common
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../common")))
try:
    from common import create_or_update_record, extract_file_id, retry_with_backoff  # type: ignore
except ImportError:
    # Fallback for if common is in same directory
    try:
        from common import (  # type: ignore
            create_or_update_record,
            extract_file_id,
            retry_with_backoff,
        )
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


def get_existing_record(table: Any, document_id: str) -> dict[str, Any] | None:
    """Check if a DynamoDB record already exists for the given document_id.

    Args:
        table: The DynamoDB table object.
        document_id: The primary key to search for.

    Returns:
        The record dictionary if found, None otherwise.
    """
    try:
        response = table.get_item(Key={"document_id": document_id})
        item = response.get("Item")
        return item if item is None or isinstance(item, dict) else dict(item)
    except Exception as e:
        logger.error(f"Error checking existing record for {document_id}: {e}")
        return None


def handle_regular_file(bucket: str, key: str) -> dict[str, Any]:
    """Handle regular file uploads (non-meta.json files).

    Processes the S3 object, extracts metadata, and updates DynamoDB.
    Handles race conditions with meta.json uploads.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        Response dictionary.
    """
    logger.info(f"Handling regular file upload for key: {key}")

    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        content_type = response["ContentType"]
        etag = response["ETag"].strip('"')

        # Extract document_id from s3key
        document_id = extract_file_id(key)

        # Check if a record already exists (from meta.json upload or API handler)
        existing_record = get_existing_record(table, document_id)

        if existing_record:
            # Update existing record
            update_data = {
                "s3key": key,
                "s3bucket": bucket,
                "content_type": content_type,
                "size": response.get("ContentLength", 0),
                "etag": etag,
                "updateddatetime": datetime.now(UTC).isoformat(),
                "has_file": "yes",
            }

            # Only use S3 key as file_name if no name is already set
            if not existing_record.get("file_name"):
                update_data["file_name"] = key.split("/")[-1]

            create_or_update_record(table, document_id, update_data, is_update=True)
            logger.info(f"Updated existing record for {document_id} (meta.json was first)")
        else:
            # Create new record
            record_data = {
                "document_id": document_id,
                "s3key": key,
                "file_name": key.split("/")[-1],
                "s3bucket": bucket,
                "content_type": content_type,
                "size": response.get("ContentLength", 0),
                "etag": etag,
                "updateddatetime": datetime.now(UTC).isoformat(),
                "has_file": "yes",
            }

            try:
                # Try to create new record with condition to prevent overwrites
                create_or_update_record(table, document_id, record_data, is_update=False)
                logger.info(f"Created new record for {document_id}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    # Race condition: meta.json was processed concurrently
                    logger.info(f"Race condition for {document_id}. Record created concurrently.")

                    # Retry with backoff: re-read the record and update it
                    def retry_as_update() -> None:
                        existing = get_existing_record(table, document_id)
                        if existing:
                            update_data = {
                                "s3key": key,
                                "s3bucket": bucket,
                                "content_type": content_type,
                                "size": response.get("ContentLength", 0),
                                "etag": etag,
                                "updateddatetime": datetime.now(UTC).isoformat(),
                                "has_file": "yes",
                            }
                            if not existing.get("file_name"):
                                update_data["file_name"] = key.split("/")[-1]

                            create_or_update_record(table, document_id, update_data, is_update=True)
                            logger.info(f"Successfully updated {document_id} after race condition")
                        else:
                            raise Exception(f"Record disappeared for {document_id}")

                    retry_with_backoff(retry_as_update, max_attempts=3, initial_delay=0.5)
                else:
                    raise

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "File processed successfully",
                    "s3key": key,
                    "content_type": content_type,
                    "etag": etag,
                }
            ),
        }

    except Exception as e:
        logger.error(f"Error processing object {key} from bucket {bucket}: {e}")
        raise e


def handle_meta_json_file(bucket: str, key: str) -> dict[str, Any]:
    """Handle meta.json file uploads to update existing file records.

    Extracts metadata from the JSON file and updates DynamoDB.
    Handles race conditions with regular file uploads.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        Response dictionary.
    """
    # Extract document_id from the meta.json key (format: {document_id}.meta.json)
    document_id = extract_file_id(key[:-10])
    logger.info(f"Handling meta.json file upload for document_id: {document_id}")

    try:
        # Download and parse the meta.json file
        response = s3.get_object(Bucket=bucket, Key=key)
        meta_content = response["Body"].read().decode("utf-8")
        meta_data = json.loads(meta_content)
        etag = response["ETag"].strip('"')

        # Check if record already exists
        existing_record = get_existing_record(table, document_id)

        if existing_record:
            # Update existing record
            update_data = {
                "meta_s3key": key,
                "meta_json_timestamp": datetime.now(UTC).isoformat(),
                "has_metadata": "yes",
                **meta_data,
            }
            create_or_update_record(table, document_id, update_data, is_update=True)
            logger.info(f"Updated existing record for {document_id} with metadata")
        else:
            # Create new record (meta.json uploaded first)
            record_data = {
                "document_id": document_id,
                "meta_s3key": key,
                "meta_json_timestamp": datetime.now(UTC).isoformat(),
                "has_metadata": "yes",
                **meta_data,
            }

            try:
                # Try to create new record with condition to prevent overwrites
                create_or_update_record(table, document_id, record_data, is_update=False)
                logger.info(f"Created new record for {document_id} from metadata")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    # Race condition: regular file was processed concurrently
                    logger.info(f"Race condition for {document_id}. Record created concurrently.")

                    # Retry with backoff
                    def retry_as_update() -> None:
                        existing = get_existing_record(table, document_id)
                        if existing:
                            update_data = {
                                "meta_s3key": key,
                                "meta_json_timestamp": datetime.now(UTC).isoformat(),
                                "has_metadata": "yes",
                                **meta_data,
                            }
                            create_or_update_record(table, document_id, update_data, is_update=True)
                            logger.info(
                                f"Successfully updated {document_id} with metadata after race"
                            )
                        else:
                            raise Exception(f"Record disappeared for {document_id}")

                    retry_with_backoff(retry_as_update, max_attempts=3, initial_delay=0.5)
                else:
                    raise

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Meta file processed successfully",
                    "document_id": document_id,
                    "meta_s3key": key,
                    "etag": etag,
                    "deleted_from_s3": False,
                }
            ),
        }

    except Exception as e:
        logger.error(f"Error processing meta.json {key} from {bucket}: {e}")
        raise e


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process S3 object created events.

    Args:
        event: S3 EventBridge event.
        context: Lambda context object.

    Returns:
        Lambda response object.
    """
    try:
        # Parse EventBridge event
        bucket = event["detail"]["bucket"]["name"]
        key = event["detail"]["object"]["key"]

        # Skip folder creation events
        if key.endswith("/"):
            return {"statusCode": 200, "body": "Folder event ignored"}

        # Check if this is a meta.json file
        if key.endswith(".meta.json"):
            return handle_meta_json_file(bucket, key)
        else:
            return handle_regular_file(bucket, key)

    except Exception as e:
        logger.exception(f"Error processing event: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Internal server error", "error": str(e)}),
        }
