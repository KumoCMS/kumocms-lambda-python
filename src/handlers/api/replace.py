import base64
import binascii
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import boto3
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
    "Access-Control-Allow-Methods": "PUT,OPTIONS",
}


def create_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
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
        "body": json.dumps(body),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle document replacement requests (PUT /documents/{id}).

    Updated existing document metadata in DynamoDB and overwrites S3 object.

    Args:
        event: API Gateway event dictionary.
        context: Lambda context object.

    Returns:
        API Gateway response dictionary.
    """
    try:
        # Get document ID from path
        path_params = event.get("pathParameters", {})
        if not path_params or not path_params.get("id"):
            return create_response(400, {"error": "Document ID is required in path"})

        document_id = unquote(path_params["id"])

        # Parse request body
        body_str = event.get("body", "{}")
        body = json.loads(body_str)

        # Get file data
        file_content = body.get("file_content")  # Base64 encoded
        file_name = body.get("file_name")
        content_type = body.get("content_type", "application/octet-stream")
        file_size = body.get("file_size")

        # Get meta.json data
        meta_content = body.get("meta_content")  # Base64 encoded
        meta_json = body.get("meta_json")  # Already parsed JSON object

        # Validate required fields
        if not file_name:
            return create_response(400, {"error": "File name required"})

        if not meta_content and not meta_json:
            return create_response(400, {"error": "meta.json file required"})

        # Parse meta.json if provided as base64
        if meta_content:
            try:
                meta_data_bytes = base64.b64decode(meta_content)
                meta_json = json.loads(meta_data_bytes.decode("utf-8"))
            except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.error(f"Invalid meta.json format: {str(e)}")
                return create_response(400, {"error": f"Invalid meta.json format: {str(e)}"})

        # Extract file extension from original filename
        file_extension = ""
        if "." in file_name:
            file_extension = file_name.rsplit(".", 1)[1]

        # Generate S3 keys with document_id
        document_s3_key = f"{document_id}.{file_extension}" if file_extension else document_id
        meta_s3_key = f"{document_id}.meta.json"

        # Check if we should use presigned URL (file >= 10MB)
        if file_size and int(file_size) >= MAX_FILE_SIZE:
            presigned_url = s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": S3_BUCKET,
                    "Key": document_s3_key,
                    "ContentType": content_type,
                },
                ExpiresIn=3600,
            )

            # Save metadata to DynamoDB
            table = dynamodb.Table(DOCUMENTS_TABLE)
            table.put_item(
                Item={
                    "document_id": document_id,
                    "s3key": document_s3_key,
                    "file_name": file_name,
                    "original_file_name": file_name,
                    "s3bucket": S3_BUCKET,
                    "meta_s3key": meta_s3_key,
                    "size": int(file_size),
                    "content_type": content_type,
                    "updateddatetime": datetime.now(UTC).isoformat(),
                    "has_metadata": "yes",
                    **(meta_json if meta_json else {}),
                }
            )
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

        # Direct upload for files < 10MB
        if not file_content:
            return create_response(400, {"error": "File content required for direct upload"})

        # Decode file content
        file_data = base64.b64decode(file_content)

        # Upload meta.json file to S3
        meta_json_str = json.dumps(meta_json)
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=meta_s3_key,
            Body=meta_json_str.encode("utf-8"),
            ContentType="application/json",
        )
        logger.info(f"Successfully uploaded {meta_s3_key} to S3")

        # Upload document to S3
        response = s3.put_object(
            Bucket=S3_BUCKET,
            Key=document_s3_key,
            Body=file_data,
            ContentType=content_type,
        )

        # Verify upload was successful
        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            raise Exception(
                f"S3 upload failed with status: {response['ResponseMetadata']['HTTPStatusCode']}"
            )

        etag = response.get("ETag", "unknown")
        logger.info(f"Successfully uploaded {document_s3_key} to S3. ETag: {etag}")

        # Save metadata to DynamoDB
        table = dynamodb.Table(DOCUMENTS_TABLE)
        table.put_item(
            Item={
                "document_id": document_id,
                "s3key": document_s3_key,
                "file_name": file_name,
                "original_file_name": file_name,
                "s3bucket": S3_BUCKET,
                "meta_s3key": meta_s3_key,
                "size": len(file_data),
                "content_type": content_type,
                "updateddatetime": datetime.now(UTC).isoformat(),
                "has_metadata": "yes",
                **(meta_json if meta_json else {}),
            }
        )
        logger.info(f"Saved metadata to DynamoDB for document_id: {document_id}")

        return create_response(
            200,
            {
                "document_id": document_id,
                "message": "File replaced successfully",
                "method": "direct",
            },
        )

    except Exception as e:
        logger.exception(
            f"Replace error for {document_id if 'document_id' in locals() else 'unknown'}: {e}"
        )
        return create_response(500, {"error": "Replace failed", "details": str(e)})
