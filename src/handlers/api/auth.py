import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import boto3

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb")

# Environment variables
USERS_TABLE = os.environ.get("USERS_TABLE", "")

# Common headers
COMMON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def simple_hash(password: str) -> str:
    """Simple password hashing for demonstration purposes.

    Args:
        password: The plain text password.

    Returns:
        Hexadecimal representation of the SHA-256 hash.
    """
    return hashlib.sha256(password.encode()).hexdigest()


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
    """Handle authentication requests.

    Args:
        event: API Gateway event dictionary.
        context: Lambda context object.

    Returns:
        API Gateway response dictionary.
    """
    try:
        # Parse request body
        try:
            body = json.loads(event.get("body", "{}"))
        except json.JSONDecodeError:
            return create_response(400, {"error": "Invalid JSON"})

        username = body.get("username")
        password = body.get("password")

        if not username or not password:
            return create_response(400, {"error": "Username and password required"})

        # Get user from database
        table = dynamodb.Table(USERS_TABLE)
        try:
            response = table.get_item(Key={"username": username})
            user = response.get("Item")
        except Exception as e:
            logger.error(f"Failed to query user {username}: {e}")
            return create_response(500, {"error": "Internal server error"})

        if not user:
            logger.warning(f"Auth attempt for non-existent user: {username}")
            return create_response(401, {"error": "Invalid credentials"})

        # Check credentials
        stored_password = user.get("password", "")
        if simple_hash(password) == stored_password:
            # Note: We use the stored API Key as the token for simple mapping
            api_key = user.get("api_key")

            if not api_key:
                logger.error(f"User {username} has no API key configured")
                return create_response(500, {"error": "User configuration error"})

            # Update last login timestamp
            try:
                table.update_item(
                    Key={"username": username},
                    UpdateExpression="SET last_login = :timestamp",
                    ExpressionAttributeValues={":timestamp": datetime.now(UTC).isoformat()},
                )
            except Exception as e:
                logger.error(f"Failed to update last login for {username}: {e}")

            return create_response(
                200,
                {
                    "token": api_key,  # Compatibility with clients expecting 'token'
                    "user": {
                        "username": username,
                        "email": user.get("email"),
                        "role": user.get("role", "user"),
                        "permissions": user.get("permissions", []),
                    },
                },
            )
        else:
            logger.warning(f"Invalid password for user: {username}")
            return create_response(401, {"error": "Invalid credentials"})

    except Exception as e:
        logger.exception(f"Auth error for {username if 'username' in locals() else 'unknown'}: {e}")
        return create_response(500, {"error": "Internal server error"})
