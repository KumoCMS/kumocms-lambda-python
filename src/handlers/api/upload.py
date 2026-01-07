import base64
import binascii
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import boto3
import ulid
from botocore.client import Config

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
dynamodb = boto3.resource("dynamodb")

# Environment variables
S3_BUCKET = os.environ.get("S3_BUCKET", "")
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "")
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Common headers for API responses
COMMON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def create_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Create a standardized API Gateway response.

    Args:
        status_code: HTTP status code.
        body: Response body as a dictionary.

    Returns:
        Formatted response dictionary for API Gateway.
    """
    return {
        "statusCode": status_code,
        "headers": COMMON_HEADERS,
        "body": json.dumps(body),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle document upload requests.

    Expects metadata and file details, and returns a pre-signed URL for
    the client to upload the document directly to S3.
    1. meta.json file (or meta_content base64)
    2. File details (name, size, content type)

    Returns:
        API Gateway response dictionary with document_id and upload_url.
    """
    try:
        # Parse request body
        body_str = event.get("body", "{}")
        body = json.loads(body_str)

        # Get file data
        file_name = body.get("file_name")
        content_type = body.get("content_type", "application/octet-stream")
        file_size = body.get("file_size")

        # Get meta.json data
        meta_content = body.get("meta_content")  # Base64 encoded
        meta_json = body.get("meta_json")  # Already parsed JSON object

        # Validate required fields
        if not file_name:
            return create_response(400, {"error": "File name required"})

        # Parse meta.json if provided as base64
        if meta_content:
            try:
                meta_data_bytes = base64.b64decode(meta_content)
                meta_json = json.loads(meta_data_bytes.decode("utf-8"))
            except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.error(f"Invalid meta.json format: {str(e)}")
                return create_response(400, {"error": f"Invalid meta.json format: {str(e)}"})

        # Generate ULID as document_id (lexicographically sortable, timestamp-embedded)
        document_id = ulid.new().str

        # Extract file extension from original filename
        file_extension = ""
        if "." in file_name:
            file_extension = file_name.rsplit(".", 1)[1]

        # Generate S3 key with document_id
        document_s3_key = f"{document_id}.{file_extension}" if file_extension else document_id

        # Prepare DynamoDB item
        item = {
            "document_id": document_id,
            "s3key": document_s3_key,
            "file_name": file_name,
            "original_file_name": file_name,
            "s3bucket": S3_BUCKET,
            "content_type": content_type,
            "updateddatetime": datetime.now(UTC).isoformat(),
            "has_metadata": "no",
        }

        # Upload meta.json if data is provided
        if meta_json:
            meta_s3_key = f"{document_id}.meta.json"
            meta_json_str = json.dumps(meta_json)
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=meta_s3_key,
                Body=meta_json_str.encode("utf-8"),
                ContentType="application/json",
            )
            logger.info(f"Successfully uploaded {meta_s3_key} to S3")
            item["meta_s3key"] = meta_s3_key
            item["has_metadata"] = "yes"
            item.update(meta_json)

        # Generate presigned URL for the document upload
        presigned_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": S3_BUCKET,
                "Key": document_s3_key,
                "ContentType": content_type,
            },
            ExpiresIn=3600,
            HttpMethod="PUT",
        )

        # Only add file_size if provided
        if file_size is not None:
            item["size"] = int(file_size)

        table = dynamodb.Table(DOCUMENTS_TABLE)
        table.put_item(Item=item)
        logger.info(f"Saved metadata to DynamoDB for document_id: {document_id}")

        return create_response(
            200,
            {
                "document_id": document_id,
                "message": "Presigned URL generated",
                "upload_url": presigned_url,
                "method": "presigned_url",
            },
        )

    except Exception as e:
        logger.exception(f"Upload error: {str(e)}")
        return create_response(500, {"error": "Upload failed", "details": str(e)})
