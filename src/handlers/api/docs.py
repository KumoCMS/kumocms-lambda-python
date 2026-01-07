import json
import logging
import os
from typing import Any

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def get_openapi_spec() -> dict[str, Any]:
    """Generate OpenAPI 3.0 specification for the CMS API.

    Returns:
        A dictionary containing the OpenAPI specification.
    """
    # Get API Gateway URL from environment or use placeholder
    api_url = os.environ.get("API_GATEWAY_URL", "https://api.example.com/v1")

    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "Kumo CMS API",
            "version": "1.0.0",
            "description": (
                "Complete document management API with API Key authentication. "
                "Supports upload, retrieval, archiving, and restoration of documents."
            ),
            "contact": {"name": "Kumo CMS Support", "email": "kumocms@beegether.net"},
        },
        "servers": [{"url": api_url, "description": "Production API"}],
        "components": {
            "securitySchemes": {
                "apiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "Authorization",
                    "description": "API Key obtained from /auth endpoint. Format: Bearer <api_key>",
                }
            },
            "schemas": {
                "LoginRequest": {
                    "type": "object",
                    "required": ["username", "password"],
                    "properties": {
                        "username": {"type": "string", "example": "admin"},
                        "password": {"type": "string", "example": "ChangeMe123!"},
                    },
                },
                "LoginResponse": {
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "API key to be used for requests",
                        },
                        "user": {
                            "type": "object",
                            "properties": {
                                "username": {"type": "string"},
                                "role": {"type": "string"},
                            },
                        },
                    },
                },
                "UploadRequest": {
                    "type": "object",
                    "required": ["file_name"],
                    "properties": {
                        "file_name": {
                            "type": "string",
                            "example": "document.pdf",
                            "description": "Original file name",
                        },
                        "file_size": {
                            "type": "integer",
                            "example": 1048576,
                            "description": "File size in bytes",
                        },
                        "content_type": {
                            "type": "string",
                            "example": "application/pdf",
                            "default": "application/octet-stream",
                        },
                        "meta_content": {
                            "type": "string",
                            "format": "byte",
                            "description": "Base64 encoded meta.json file containing metadata",
                        },
                    },
                },
                "UploadResponse": {
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "UUID generated for this document",
                        },
                        "message": {"type": "string"},
                        "method": {"type": "string", "enum": ["presigned_url"]},
                        "upload_url": {
                            "type": "string",
                            "description": "Pre-signed URL for client-side upload",
                        },
                    },
                },
                "Document": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string"},
                        "file_name": {"type": "string"},
                        "storage_class": {
                            "type": "string",
                            "enum": ["STANDARD", "GLACIER", "DEEP_ARCHIVE"],
                        },
                        "restore_status": {"type": "string", "enum": ["restored", "in_progress"]},
                    },
                },
                "DocumentList": {
                    "type": "object",
                    "properties": {
                        "documents": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Document"},
                        },
                        "count": {"type": "integer"},
                    },
                },
                "HealthCheckResponse": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["healthy", "unhealthy"]},
                        "checks": {"type": "object"},
                    },
                },
                "ErrorResponse": {"type": "object", "properties": {"error": {"type": "string"}}},
            },
        },
        "paths": {
            "/auth": {
                "post": {
                    "summary": "User authentication",
                    "tags": ["Authentication"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/LoginRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/LoginResponse"}
                                }
                            },
                        },
                        "401": {"description": "Invalid credentials"},
                    },
                }
            },
            "/documents": {
                "get": {
                    "summary": "List documents",
                    "tags": ["Documents"],
                    "security": [{"apiKeyAuth": []}],
                    "responses": {
                        "200": {
                            "description": "List of documents",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/DocumentList"}
                                }
                            },
                        }
                    },
                },
                "post": {
                    "summary": "Upload document",
                    "tags": ["Documents"],
                    "security": [{"apiKeyAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/UploadRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Upload successful",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/UploadResponse"}
                                }
                            },
                        }
                    },
                },
            },
            "/documents/{id}": {
                "get": {
                    "summary": "Retrieve document",
                    "tags": ["Documents"],
                    "security": [{"apiKeyAuth": []}],
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "Document details and download link"}},
                },
                "delete": {
                    "summary": "Delete document",
                    "tags": ["Documents"],
                    "security": [{"apiKeyAuth": []}],
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "Deleted successfully"}},
                },
            },
            "/healthcheck": {
                "get": {
                    "summary": "API health check",
                    "tags": ["System"],
                    "responses": {
                        "200": {
                            "description": "Healthy",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/HealthCheckResponse"}
                                }
                            },
                        }
                    },
                }
            },
        },
    }

    return spec


def get_swagger_ui_html(spec_url: str) -> str:
    """Generate Swagger UI HTML page.

    Args:
        spec_url: The URL to the OpenAPI specification JSON.

    Returns:
        HTML content as a string.
    """
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Kumo CMS API - Swagger UI</title>
        <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5.10.5/swagger-ui.css">
        <style>
            body {{ margin: 0; padding: 0; }}
        </style>
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://unpkg.com/swagger-ui-dist@5.10.5/swagger-ui-bundle.js"></script>
        <script src="https://unpkg.com/swagger-ui-dist@5.10.5/swagger-ui-standalone-preset.js"></script>
        <script>
            window.onload = function() {{
                const ui = SwaggerUIBundle({{
                    url: "{spec_url}",
                    dom_id: '#swagger-ui',
                    deepLinking: true,
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIStandalonePreset
                    ],
                    plugins: [
                        SwaggerUIBundle.plugins.DownloadUrl
                    ],
                    layout: "StandaloneLayout"
                }});
                window.ui = ui;
            }};
        </script>
    </body>
    </html>
    """


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """API Documentation endpoint - serves OpenAPI spec or Swagger UI.

    Args:
        event: API Gateway event dictionary.
        context: Lambda context object.

    Returns:
        API Gateway response dictionary.
    """
    try:
        # Check query parameters
        query_params = event.get("queryStringParameters") or {}
        format_type = query_params.get("format", "ui")

        # Get the API Gateway URL from the request context
        request_context = event.get("requestContext", {})
        domain_name = request_context.get("domainName", "api.example.com")
        stage = request_context.get("stage", "v1")
        api_url = f"https://{domain_name}/{stage}"

        # Set API_GATEWAY_URL for the spec
        os.environ["API_GATEWAY_URL"] = api_url

        if format_type in ["json", "spec"]:
            # Return OpenAPI spec as JSON
            spec = get_openapi_spec()
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                },
                "body": json.dumps(spec, indent=2),
            }
        else:
            # Return Swagger UI HTML
            spec_url = f"{api_url}/docs?format=json"
            html = get_swagger_ui_html(spec_url)
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "text/html", "Access-Control-Allow-Origin": "*"},
                "body": html,
            }

    except Exception as e:
        logger.exception(f"Error serving documentation: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Internal server error"}),
        }
