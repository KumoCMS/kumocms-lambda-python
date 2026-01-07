import json
import logging
import os
import sys
from typing import Any
from urllib.parse import unquote

import boto3

# Add common directory to path to import common if needed
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

# Common headers for API responses
COMMON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "DELETE,OPTIONS",
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
    """Handle document deletion requests.

    Deletes document from both S3 and DynamoDB.

    Args:
        event: API Gateway event dictionary.
        context: Lambda context object.

    Returns:
        API Gateway response dictionary.
    """
    try:
        path_params = event.get("pathParameters")
        if not path_params or not path_params.get("id"):
            return create_response(400, {"error": "Document ID is required"})

        # Get document ID from path and URL decode it
        document_id = unquote(path_params["id"])

        # Get document metadata to find the S3 key
        table = dynamodb.Table(DOCUMENTS_TABLE)
        response = table.get_item(Key={"document_id": document_id})
        document = response.get("Item")

        if not document:
            return create_response(404, {"error": "Document not found"})

        # Get the s3key from the document
        s3key = document.get("s3key")

        # Delete from S3 if s3key exists
        if s3key:
            try:
                s3.delete_object(Bucket=S3_BUCKET, Key=str(s3key))
                logger.info(f"Deleted S3 object: {str(s3key)}")
            except Exception as e:
                logger.error(f"Error deleting S3 object {s3key!r}: {str(e)}")
                # Continue cleaning up DB even if S3 delete fails

        # Delete from DynamoDB
        table.delete_item(Key={"document_id": document_id})
        logger.info(f"Deleted DynamoDB record: {document_id}")

        return create_response(200, {"message": "Document deleted successfully"})

    except Exception as e:
        logger.exception(
            f"Delete error for {document_id if 'document_id' in locals() else 'unknown'}: {e}"
        )
        return create_response(500, {"error": "Deletion failed", "message": str(e)})
