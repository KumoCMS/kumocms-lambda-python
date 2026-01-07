import logging
import os
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize AWS clients
USERS_TABLE = os.environ.get("USERS_TABLE", "")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(USERS_TABLE)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """API Key Validator for API Gateway Custom Authorizer.

    Args:
        event: Authorizer event object.
        context: Lambda context object.

    Returns:
        An IAM policy statement dictionary.

    Raises:
        Exception: "Unauthorized" if the token is invalid or missing.
    """
    try:
        # Extract token from authorizationToken field
        token = event.get("authorizationToken")

        if not token:
            # Fallback for some authorizer configurations
            token = event.get("headers", {}).get("authorization")

        if not token:
            logger.warning("Auth error: No token provided in event")
            raise Exception("Unauthorized") from None

        # Remove 'Bearer ' prefix if present
        if token.lower().startswith("bearer "):
            token = token[7:].strip()

        logger.info(f"Validating API key starting with: {token[:4]}...")

        # Query DynamoDB api-key-index
        try:
            response = table.query(
                IndexName="api-key-index", KeyConditionExpression=Key("api_key").eq(token)
            )
        except Exception as e:
            logger.error(f"DynamoDB query failed for API Key validation: {e}")
            raise Exception("Unauthorized") from e

        if not response.get("Items"):
            logger.warning("Auth error: Invalid API Key")
            raise Exception("Unauthorized") from None

        user = response["Items"][0]
        username = user["username"]
        role = user.get("role", "user")

        logger.info(f"Authorized user: {str(username)}, role: {str(role)}")

        # Generate IAM policy
        policy = generate_policy(
            str(username),
            "Allow",
            event["methodArn"],
            {"username": username, "role": role},
        )

        return policy

    except Exception as e:
        if str(e) != "Unauthorized":
            logger.exception(f"Unexpected auth validation error: {e}")
        # Custom authorizers must return "Unauthorized" or a 401 response
        raise Exception("Unauthorized") from e


def generate_policy(
    principal_id: str, effect: str, resource: str, context_data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Generate API Gateway IAM policy response.

    Args:
        principal_id: The user identifier.
        effect: "Allow" or "Deny".
        resource: The ARN of the resource being invoked.
        context_data: Optional metadata to pass to the backend.

    Returns:
        Formatted policy dictionary.
    """
    # Extract the API Gateway ARN base and allow all resources on this API
    # format: arn:aws:execute-api:region:account-id:api-id/stage/method/resource-path
    api_gateway_arn = resource.split("/")[0] + "/*"

    policy: dict[str, Any] = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": "execute-api:Invoke", "Effect": effect, "Resource": api_gateway_arn}
            ],
        },
    }

    if context_data:
        policy["context"] = context_data

    return policy
