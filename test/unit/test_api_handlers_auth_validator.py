import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Set AWS environment variables BEFORE importing any modules that use boto3
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["API_KEY_SECRET_PATH"] = "test-secret-path"

# Add the src/handlers/api directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src" / "handlers" / "api"))

import auth_validator


@pytest.fixture(autouse=True)
def reset_cache_and_env():
    """Reset the secret cache and environment before each test."""
    # Save original environment
    original_env = os.environ.get("API_KEY_SECRET_PATH")

    # Set environment variable
    os.environ["API_KEY_SECRET_PATH"] = "test-secret-path"

    # Reset cache
    auth_validator._secret_cache = None

    # Reload module to pick up environment variable
    import importlib

    importlib.reload(auth_validator)

    yield

    # Restore original environment
    if original_env is not None:
        os.environ["API_KEY_SECRET_PATH"] = original_env

    # Reset cache
    auth_validator._secret_cache = None


@pytest.fixture
def mock_secrets_manager():
    """Mock Secrets Manager client."""
    with patch("auth_validator.secrets_manager") as mock_sm:
        yield mock_sm


@pytest.fixture
def valid_secret():
    """Valid secret structure with both keys."""
    return {
        "api_key": "valid-api-key-12345",
        "api_key_previous": "old-api-key-67890",
    }


@pytest.fixture
def mock_context():
    """Mock Lambda context."""
    context = Mock()
    context.function_name = "test-auth-validator"
    context.invoked_function_arn = (
        "arn:aws:lambda:us-east-1:123456789012:function:test-auth-validator"
    )
    context.request_id = "test-request-id"
    return context


class TestGetApiKeys:
    """Test the get_api_keys function."""

    def test_get_api_keys_success(self, mock_secrets_manager, valid_secret):
        """Test successful retrieval of API keys."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        result = auth_validator.get_api_keys()

        assert result == valid_secret
        mock_secrets_manager.get_secret_value.assert_called_once_with(SecretId="test-secret-path")

    def test_get_api_keys_caching(self, mock_secrets_manager, valid_secret):
        """Test that API keys are cached after first retrieval."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        # First call
        result1 = auth_validator.get_api_keys()
        # Second call should use cache
        result2 = auth_validator.get_api_keys()

        assert result1 == result2
        # Should only call Secrets Manager once
        assert mock_secrets_manager.get_secret_value.call_count == 1

    def test_get_api_keys_missing_env_var(self, mock_secrets_manager):
        """Test error when API_KEY_SECRET_PATH is not set."""
        with patch.dict(os.environ, {"API_KEY_SECRET_PATH": ""}):
            # Reset module to pick up env change
            import importlib

            importlib.reload(auth_validator)
            auth_validator._secret_cache = None

            with pytest.raises(Exception, match="Configuration error"):
                auth_validator.get_api_keys()

    def test_get_api_keys_empty_secret(self, mock_secrets_manager):
        """Test error when secret value is empty."""
        mock_secrets_manager.get_secret_value.return_value = {"SecretString": ""}

        with pytest.raises(Exception, match="Configuration error"):
            auth_validator.get_api_keys()

    def test_get_api_keys_missing_api_key_field(self, mock_secrets_manager):
        """Test error when secret is missing required api_key field."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps({"api_key_previous": "old-key"})
        }

        with pytest.raises(Exception, match="Configuration error"):
            auth_validator.get_api_keys()

    def test_get_api_keys_invalid_json(self, mock_secrets_manager):
        """Test error when secret contains invalid JSON."""
        mock_secrets_manager.get_secret_value.return_value = {"SecretString": "not-valid-json"}

        with pytest.raises(Exception, match="Configuration error"):
            auth_validator.get_api_keys()

    def test_get_api_keys_secrets_manager_error(self, mock_secrets_manager):
        """Test error handling when Secrets Manager fails."""
        mock_secrets_manager.get_secret_value.side_effect = Exception("Secrets Manager unavailable")

        with pytest.raises(Exception, match="Configuration error"):
            auth_validator.get_api_keys()

    def test_get_api_keys_only_current_key(self, mock_secrets_manager):
        """Test retrieval when only current API key is present."""
        secret = {"api_key": "current-key-only"}
        mock_secrets_manager.get_secret_value.return_value = {"SecretString": json.dumps(secret)}

        result = auth_validator.get_api_keys()

        assert result == secret
        assert "api_key" in result
        assert "api_key_previous" not in result


class TestLambdaHandler:
    """Test the lambda_handler function."""

    def test_auth_success_with_current_key(self, mock_secrets_manager, valid_secret, mock_context):
        """Test successful authentication with current API key."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        event = {
            "authorizationToken": "Bearer valid-api-key-12345",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        result = auth_validator.lambda_handler(event, mock_context)

        assert result["principalId"] == "api-user"
        assert result["policyDocument"]["Version"] == "2012-10-17"
        assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
        assert result["context"]["authenticated"] == "true"
        assert result["context"]["key_type"] == "current"

    def test_auth_success_with_previous_key(self, mock_secrets_manager, valid_secret, mock_context):
        """Test successful authentication with previous API key (rotation support)."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        event = {
            "authorizationToken": "Bearer old-api-key-67890",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        result = auth_validator.lambda_handler(event, mock_context)

        assert result["principalId"] == "api-user"
        assert result["context"]["authenticated"] == "true"
        assert result["context"]["key_type"] == "previous"

    def test_auth_success_without_bearer_prefix(
        self, mock_secrets_manager, valid_secret, mock_context
    ):
        """Test successful authentication without Bearer prefix."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        event = {
            "authorizationToken": "valid-api-key-12345",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        result = auth_validator.lambda_handler(event, mock_context)

        assert result["principalId"] == "api-user"
        assert result["context"]["key_type"] == "current"

    def test_auth_failure_invalid_key(self, mock_secrets_manager, valid_secret, mock_context):
        """Test authentication failure with invalid API key."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        event = {
            "authorizationToken": "Bearer invalid-key-99999",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        with pytest.raises(Exception, match="Unauthorized"):
            auth_validator.lambda_handler(event, mock_context)

    def test_auth_failure_missing_token(self, mock_context):
        """Test authentication failure when token is missing."""
        event = {
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        with pytest.raises(Exception, match="Unauthorized"):
            auth_validator.lambda_handler(event, mock_context)

    def test_auth_fallback_to_headers(self, mock_secrets_manager, valid_secret, mock_context):
        """Test token extraction from headers as fallback."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        event = {
            "headers": {"authorization": "Bearer valid-api-key-12345"},
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        result = auth_validator.lambda_handler(event, mock_context)

        assert result["principalId"] == "api-user"
        assert result["context"]["authenticated"] == "true"

    def test_auth_failure_secrets_manager_error(self, mock_secrets_manager, mock_context):
        """Test authentication failure when Secrets Manager fails."""
        mock_secrets_manager.get_secret_value.side_effect = Exception("Secrets Manager error")

        event = {
            "authorizationToken": "Bearer some-key",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        with pytest.raises(Exception, match="Unauthorized"):
            auth_validator.lambda_handler(event, mock_context)

    def test_auth_case_insensitive_bearer(self, mock_secrets_manager, valid_secret, mock_context):
        """Test that Bearer prefix is case-insensitive."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        event = {
            "authorizationToken": "bearer valid-api-key-12345",  # lowercase
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        result = auth_validator.lambda_handler(event, mock_context)

        assert result["principalId"] == "api-user"

    def test_auth_empty_token(self, mock_context):
        """Test authentication failure with empty token."""
        event = {
            "authorizationToken": "",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        with pytest.raises(Exception, match="Unauthorized"):
            auth_validator.lambda_handler(event, mock_context)

    def test_auth_bearer_only(self, mock_context):
        """Test authentication failure with only 'Bearer' prefix and no key."""
        event = {
            "authorizationToken": "Bearer ",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        with pytest.raises(Exception, match="Unauthorized"):
            auth_validator.lambda_handler(event, mock_context)


class TestGeneratePolicy:
    """Test the generate_policy function."""

    def test_generate_policy_basic(self):
        """Test basic policy generation."""
        resource = "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents"

        policy = auth_validator.generate_policy("test-user", "Allow", resource)

        assert policy["principalId"] == "test-user"
        assert policy["policyDocument"]["Version"] == "2012-10-17"
        assert len(policy["policyDocument"]["Statement"]) == 1
        statement = policy["policyDocument"]["Statement"][0]
        assert statement["Action"] == "execute-api:Invoke"
        assert statement["Effect"] == "Allow"
        assert statement["Resource"].endswith("/*")

    def test_generate_policy_with_context(self):
        """Test policy generation with context data."""
        resource = "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents"
        context_data = {"authenticated": "true", "role": "admin"}

        policy = auth_validator.generate_policy("test-user", "Allow", resource, context_data)

        assert policy["context"] == context_data

    def test_generate_policy_deny(self):
        """Test policy generation with Deny effect."""
        resource = "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents"

        policy = auth_validator.generate_policy("test-user", "Deny", resource)

        assert policy["policyDocument"]["Statement"][0]["Effect"] == "Deny"

    def test_generate_policy_wildcard_resource(self):
        """Test that policy allows all resources in the API."""
        resource = "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents"

        policy = auth_validator.generate_policy("test-user", "Allow", resource)

        # Should convert to wildcard
        assert policy["policyDocument"]["Statement"][0]["Resource"] == (
            "arn:aws:execute-api:us-east-1:123456789012:abcdef123/*"
        )

    def test_generate_policy_no_context(self):
        """Test policy generation without context data."""
        resource = "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents"

        policy = auth_validator.generate_policy("test-user", "Allow", resource)

        assert "context" not in policy or policy.get("context") is None


class TestAuthValidatorIntegration:
    """Integration tests for the auth validator."""

    def test_full_auth_flow_current_key(self, mock_secrets_manager, valid_secret, mock_context):
        """Test complete authentication flow with current API key."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        event = {
            "authorizationToken": "Bearer valid-api-key-12345",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/POST/documents",
        }

        result = auth_validator.lambda_handler(event, mock_context)

        # Verify policy structure
        assert "principalId" in result
        assert "policyDocument" in result
        assert "context" in result

        # Verify policy allows access
        assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"

        # Verify context
        assert result["context"]["authenticated"] == "true"
        assert result["context"]["key_type"] == "current"

    def test_full_auth_flow_previous_key(self, mock_secrets_manager, valid_secret, mock_context):
        """Test complete authentication flow with previous API key."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        event = {
            "authorizationToken": "Bearer old-api-key-67890",
            "methodArn": (
                "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/DELETE/documents/123"
            ),
        }

        result = auth_validator.lambda_handler(event, mock_context)

        # Verify it indicates previous key was used
        assert result["context"]["key_type"] == "previous"
        assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"

    def test_multiple_requests_use_cache(self, mock_secrets_manager, valid_secret, mock_context):
        """Test that multiple requests use cached secrets."""
        mock_secrets_manager.get_secret_value.return_value = {
            "SecretString": json.dumps(valid_secret)
        }

        event = {
            "authorizationToken": "Bearer valid-api-key-12345",
            "methodArn": "arn:aws:execute-api:us-east-1:123456789012:abcdef123/prod/GET/documents",
        }

        # Make multiple requests
        auth_validator.lambda_handler(event, mock_context)
        auth_validator.lambda_handler(event, mock_context)
        auth_validator.lambda_handler(event, mock_context)

        # Should only call Secrets Manager once due to caching
        assert mock_secrets_manager.get_secret_value.call_count == 1
