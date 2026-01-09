import json
import logging
import os
from typing import Any

import boto3

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize AWS clients
SECRET_PATH = os.environ.get("API_KEY_SECRET_PATH", "")
secrets_manager = boto3.client("secretsmanager")

# Cache for the secret to avoid repeated API calls
_secret_cache: dict[str, Any] | None = None


def get_api_keys() -> dict[str, str]:
    """Retrieve API keys from AWS Secrets Manager.

    Returns:
        Dictionary containing api_key and api_key_previous.

    Raises:
        Exception: If secret retrieval fails or secret format is invalid.
    """
    global _secret_cache

    # Return cached secret if available
    if _secret_cache is not None:
        return _secret_cache

    if not SECRET_PATH:
        logger.error("API_KEY_SECRET_PATH environment variable not set")
        raise Exception("Configuration error")

    try:
        response = secrets_manager.get_secret_value(SecretId=SECRET_PATH)
        secret_string = response.get("SecretString")

        if not secret_string:
            logger.error("Secret value is empty")
            raise Exception("Configuration error")

        secret_data = json.loads(secret_string)

        # Validate secret structure
        if "api_key" not in secret_data:
            logger.error("Secret missing required 'api_key' field")
            raise Exception("Configuration error")

        # Cache the secret
        _secret_cache = secret_data
        logger.info("Successfully retrieved and cached API keys from Secrets Manager")

        return secret_data

    except Exception as e:
        logger.error(f"Failed to retrieve secret from Secrets Manager: {e}")
        raise Exception("Configuration error") from e


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

        # Get API keys from Secrets Manager
        try:
            api_keys = get_api_keys()
        except Exception as e:
            logger.error(f"Failed to retrieve API keys: {e}")
            raise Exception("Unauthorized") from e

        # Validate token against both current and previous API keys
        valid_api_key = api_keys.get("api_key")
        previous_api_key = api_keys.get("api_key_previous")

        if token != valid_api_key and token != previous_api_key:
            logger.warning("Auth error: Invalid API Key")
            raise Exception("Unauthorized") from None

        # Determine which key was used
        key_type = "current" if token == valid_api_key else "previous"
        logger.info(f"Authorized with {key_type} API key")

        # Generate IAM policy with generic principal
        policy = generate_policy(
            "api-user",
            "Allow",
            event["methodArn"],
            {"authenticated": "true", "key_type": key_type},
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
