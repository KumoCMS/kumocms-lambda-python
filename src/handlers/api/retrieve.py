import json
import logging
import os
import sys
from decimal import Decimal
from typing import Any, cast
from urllib.parse import unquote

import boto3
from botocore.client import Config

# Add common directory to path to import common
# This ensures common utilities are available in the Lambda environment
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
s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
dynamodb = boto3.resource("dynamodb")

# Environment variables
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")

# Common headers for API responses
COMMON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
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
    """Handle document retrieval requests.

    Supports both listing documents and retrieving specific document by ID.

    Args:
        event: API Gateway event dictionary.
        context: Lambda context object.

    Returns:
        API Gateway response dictionary.
    """
    try:
        # Check if this is a list request (no path parameters)
        path_params = event.get("pathParameters") or {}
        if not path_params or not path_params.get("id"):
            # List documents with a limit of 100
            table = dynamodb.Table(DOCUMENTS_TABLE)
            # Scan with limit to avoid scanning huge tables
            response = table.scan(Limit=100)
            documents = response.get("Items", [])

            # Filter out documents where S3 files no longer exist
            valid_documents = []
            for doc in documents:
                try:
                    # Check if S3 object exists and get storage class
                    s3_metadata = s3.head_object(Bucket=S3_BUCKET, Key=str(doc["s3key"]))

                    # Update storage_class from S3 if not present or out of sync
                    s3_storage_class = s3_metadata.get("StorageClass", "STANDARD")
                    if doc.get("storage_class") != s3_storage_class:
                        doc["storage_class"] = s3_storage_class

                    # Check restore status from S3
                    restore_info = s3_metadata.get("Restore")
                    if restore_info:
                        if 'ongoing-request="false"' in restore_info:
                            doc["restore_status"] = "restored"
                        elif 'ongoing-request="true"' in restore_info:
                            doc["restore_status"] = "in_progress"
                    elif doc.get("storage_class") in ["GLACIER", "DEEP_ARCHIVE"]:
                        # Archived but no restore info means not restored
                        if "restore_status" in doc:
                            del doc["restore_status"]

                    # Normalize filename for response
                    if "original_file_name" in doc:
                        doc["file_name"] = doc["original_file_name"]

                    valid_documents.append(doc)
                except s3.exceptions.NoSuchKey:
                    # S3 file doesn't exist, remove from DynamoDB
                    doc_id = str(doc.get("document_id", "unknown"))
                    logger.warning(f"Removing orphaned record: {doc_id}")
                    if "document_id" in doc:
                        table.delete_item(Key={"document_id": doc["document_id"]})
                except Exception as e:
                    s_key = str(doc.get("s3key", "unknown"))
                    logger.error(f"Error checking S3 object {s_key}: {str(e)}")

            return create_response(
                200,
                {
                    "documents": valid_documents,
                    "count": len(valid_documents),
                    "note": "List results limited to 100 items",
                },
            )

        # Get document ID from path and URL decode it
        document_id = unquote(path_params["id"])

        # Get document metadata
        table = dynamodb.Table(DOCUMENTS_TABLE)
        # Use type: ignore for dynamodb get_item as stubs can be tricky with Table
        response = table.get_item(Key={"document_id": document_id})  # type: ignore
        document = cast("dict[str, Any] | None", response.get("Item"))

        if not document:
            return create_response(404, {"error": "Document not found"})

        # Get the s3key and original filename from the document
        s3key = str(document.get("s3key", document_id))
        raw_original = document.get("original_file_name")
        raw_file_name = document.get("file_name", "unknown")
        original_file_name = str(raw_original or raw_file_name)

        # Check storage class/restore status
        storage_class = "STANDARD"
        try:
            # Check S3 status for the most up-to-date info
            s3_metadata = s3.head_object(Bucket=S3_BUCKET, Key=s3key)
            storage_class = s3_metadata.get("StorageClass", "STANDARD")
            restore_info = s3_metadata.get("Restore")

            if storage_class in ["GLACIER", "DEEP_ARCHIVE"]:
                if not restore_info:
                    return create_response(
                        403,
                        {
                            "message": "Please call restore api to restore the file first.",
                            "storage_class": storage_class,
                        },
                    )
                elif 'ongoing-request="true"' in restore_info:
                    return create_response(
                        202,
                        {
                            "message": "Restore is in progress. Please try again later.",
                            "restore_status": "in_progress",
                        },
                    )
                # Else: ongoing-request="false", meaning it's restored and available for download

        except s3.exceptions.NoSuchKey:
            return create_response(404, {"error": "File not found in storage"})
        except Exception as e:
            logger.error(f"Error checking S3 metadata for {s3key}: {e}")
            # Continue anyway, let generate_presigned_url fail if there's a real issue

        # Generate presigned URL with 60 second TTL
        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": s3key,
                "ResponseContentDisposition": f'attachment; filename="{original_file_name}"',
            },
            ExpiresIn=60,
        )

        # Build response body with full metadata
        response_body: dict[str, Any] = dict(document).copy()
        response_body["file_name"] = original_file_name
        response_body["presigned_url"] = presigned_url
        response_body["storage_class"] = storage_class

        # Return complete metadata including presigned URL
        return create_response(200, response_body)

    except Exception as e:
        logger.exception(f"Retrieve error: {str(e)}")
        return create_response(500, {"error": "Retrieval failed", "message": str(e)})
