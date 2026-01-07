# Kumo CMS Lambda Functions - Gemini Project Context

## Project Overview
This repository contains the serverless backend for a Document Management System (DMS) built for the Kumo CMS project. It provides a robust, production-ready set of AWS Lambda functions for managing document lifecycles, including upload, retrieval, archiving (Glacier), and restoration.

## Core Technology Stack
- **Language**: Python 3.14 (Latest stable features and performance)
- **Infrastructure**: AWS Lambda, S3, DynamoDB, EventBridge, SQS, API Gateway
- **Tooling**:
  - **Linting/Formatting**: Ruff (replaces Flake8, Isort, and Black for high performance)
  - **Type Checking**: Mypy (Strict type safety)
  - **Testing**: Pytest with Moto (for AWS mocking)
  - **Versioning**: Semantic Release with Conventional Commits

## Project Structure
```
src/
├── common/             # Shared utilities (retry logic, DDB helper)
├── handlers/
│   ├── api/            # API Gateway Lambda handlers
│   │   ├── auth.py     # API Key authentication
│   │   ├── docs.py     # Self-generating OpenAPI specification
│   │   └── ...         # Domain handlers (upload, retrieve, etc.)
│   └── events/         # EventBridge processors
│       ├── event_processor.py      # S3 metadata extraction
│       └── dlq_retry_processor.py  # Automated SQS/DLQ retries
test/
└── unit/               # Comprehensive unit tests with mocking
```

## Established Patterns & Standards

### 1. Robust Metadata Management
- **ULID IDs**: All documents use ULIDs (`ulid-py`) for lexicographical sorting and unique identification.
- **Race Condition Safety**: Uses DynamoDB `ConditionExpression` to prevent overwriting metadata during concurrent file and `meta.json` uploads.

### 2. Standardized Responses
All API handlers use a common `create_response` utility to ensure:
- Consistent status codes
- Proper CORS headers (`Access-Control-Allow-Origin: *`)
- Standardized error bodies (`{"error": "...", "message": "..."}`)
- Decimal serialization for DynamoDB numbers

### 3. Progressive Error Handling
- **Retry Logic**: `common.retry_with_backoff` handles transient AWS service errors.
- **DLQ Processors**: Failed events are routed to DLQs and periodically re-invoked by the `dlq_retry_processor`.

### 4. Code Quality Standards
- **Strict Typing**: All functions must have type hints.
- **Documentation**: Google-style docstrings for all modules and functions.
- **Structured Logging**: Use the standard `logging` module; `print()` is prohibited.

## Maintenance & CI/CD
- **Automated Checks**: Ruff and Mypy are integrated into the GitHub Actions `check_pull_request` workflow.
- **Semantic Release**: Versioning is automated based on commit prefix (`feat:`, `fix:`, `BREAKING CHANGE:`).
- **Environment**: AWS runtime should be configured for Python 3.12 (or 3.14 when available in your region).

## Deployment Context
These functions are typically deployed via Terraform. The `lambda_function.zip` artifact is generated during the CI/CD release process.

---
**Last Updated**: 2026-01-06
**Context State**: Production Refactored
