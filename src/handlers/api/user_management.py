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
}


def simple_hash(password: str) -> str:
    """Simple password hashing.

    Note: In a production environment, use a stronger hashing algorithm
    like Argon2 or bcrypt with a unique salt.

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
    """Handle user management operations.

    Args:
        event: API Gateway event dictionary.
        context: Lambda context object.

    Returns:
        API Gateway response dictionary.
    """
    try:
        http_method = event.get("httpMethod")
        path = event.get("path", "")

        if http_method == "POST" and "/users" in path:
            return create_user(event)
        elif http_method == "PUT" and "/users/" in path:
            return update_user(event)
        elif http_method == "GET" and "/users" in path:
            return list_users()
        else:
            return create_response(404, {"error": "Endpoint not found"})

    except Exception as e:
        logger.exception(f"User management error: {e}")
        return create_response(500, {"error": "Internal server error"})


def create_user(event: dict[str, Any]) -> dict[str, Any]:
    """Create new user.

    Args:
        event: API Gateway event dictionary.

    Returns:
        API Gateway response dictionary.
    """
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON"})

    username = body.get("username")
    email = body.get("email")
    password = body.get("password", "ChangeMe123!")
    role = body.get("role", "user")

    if not username or not email:
        return create_response(400, {"error": "Username and email required"})

    table = dynamodb.Table(USERS_TABLE)

    # Check if user exists
    response = table.get_item(Key={"username": username})
    if "Item" in response:
        return create_response(409, {"error": "User already exists"})

    # Create user
    permissions = ["read", "write", "delete", "admin"] if role == "admin" else ["read"]

    try:
        table.put_item(
            Item={
                "username": username,
                "email": email,
                "password": simple_hash(password),
                "role": role,
                "active": True,
                "permissions": permissions,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        logger.info(f"User created: {username}")
    except Exception as e:
        logger.error(f"Failed to create user {username}: {e}")
        raise

    return create_response(
        201, {"message": "User created successfully", "username": username, "role": role}
    )


def update_user(event: dict[str, Any]) -> dict[str, Any]:
    """Update user password.

    Args:
        event: API Gateway event dictionary.

    Returns:
        API Gateway response dictionary.
    """
    path_parameters = event.get("pathParameters")
    if not path_parameters or "username" not in path_parameters:
        return create_response(400, {"error": "Username parameter required"})

    username = path_parameters["username"]
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON"})

    new_password = body.get("password")
    if not new_password:
        return create_response(400, {"error": "Password required"})

    table = dynamodb.Table(USERS_TABLE)

    # Update password
    try:
        table.update_item(
            Key={"username": username},
            UpdateExpression="SET password = :pwd, updated_at = :time",
            ExpressionAttributeValues={
                ":pwd": simple_hash(new_password),
                ":time": datetime.now(UTC).isoformat(),
            },
        )
        logger.info(f"Password updated for user: {username}")
    except Exception as e:
        logger.error(f"Failed to update password for {username}: {e}")
        raise

    return create_response(200, {"message": "Password updated successfully"})


def list_users() -> dict[str, Any]:
    """List all users (admin only).

    Returns:
        API Gateway response dictionary.
    """
    try:
        table = dynamodb.Table(USERS_TABLE)
        response = table.scan()
        users: list[dict[str, Any]] = []

        for item in response.get("Items", []):
            users.append(
                {
                    "username": item.get("username"),
                    "email": item.get("email"),
                    "role": item.get("role"),
                    "active": item.get("active"),
                    "created_at": item.get("created_at"),
                }
            )

        return create_response(200, {"users": users})
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise
