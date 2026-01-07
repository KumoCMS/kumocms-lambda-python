# Kumo CMS Lambda Functions - Project Context

## Project Overview

This is a serverless document management system built on AWS Lambda for the Kumo CMS project. The system provides API endpoints for document upload, retrieval, archiving, restoration, and management, with event-driven processing for metadata extraction and storage.

## Architecture

### Technology Stack
- **Runtime**: Python 3.14
- **Cloud Provider**: AWS
- **Services Used**:
  - AWS Lambda (compute)
  - Amazon S3 (document storage)
  - Amazon DynamoDB (metadata storage)
  - Amazon EventBridge (event routing)
  - Amazon SQS (dead letter queues)
  - Amazon API Gateway (REST API)

### Project Structure

```
kumocms-lambda-python/
├── src/
│   ├── common/              # Shared utilities
│   │   ├── __init__.py
│   │   └── common.py        # Helper functions (retry, DynamoDB utils)
│   ├── handlers/
│   │   ├── api/             # API Lambda handlers
│   │   │   ├── archive.py   # Archive documents to Glacier
│   │   │   ├── auth.py      # Authentication
│   │   │   ├── auth_validator.py
│   │   │   ├── delete.py    # Delete documents
│   │   │   ├── docs.py      # API documentation
│   │   │   ├── healthcheck.py
│   │   │   ├── replace.py   # Replace existing documents
│   │   │   ├── restore.py   # Restore from Glacier
│   │   │   ├── retrieve.py  # Download documents
│   │   │   ├── upload.py    # Upload documents
│   │   │   └── user_management.py
│   │   └── events/          # Event-driven processors
│   │       ├── event_processor.py        # Process S3 object created events
│   │       ├── restore_event_processor.py # Process S3 restore events
│   │       └── dlq_retry_processor.py    # Retry failed events
├── test/
│   └── unit/                # Unit tests with mocking
├── .github/
│   └── workflows/           # CI/CD pipelines
│       ├── check_pull_request.yml
│       └── release.yml
├── requirements.txt         # Lambda dependencies
├── requirements-test.txt    # Test dependencies
└── package.json            # Semantic release configuration

```

## Key Components

### 1. Upload Flow
- Client uploads document + meta.json
- For files < 10MB: Direct upload to S3
- For files >= 10MB: Pre-signed URL returned for client-side upload
- S3 ObjectCreated event triggers EventBridge
- `event_processor.py` extracts metadata and stores in DynamoDB
- Document ID is ULID (lexicographically sortable, timestamp-embedded)

### 2. Retrieval Flow
- Client requests document by `document_id`
- Lambda queries DynamoDB for metadata
- Generates pre-signed S3 URL for download
- Returns URL with proper Content-Disposition header

### 3. Archive/Restore Flow
- Archive: Transitions S3 object to Glacier storage class
- Restore: Initiates Glacier restore, returns 202 while in progress
- S3 ObjectRestored event triggers restore event processor
- Updates DynamoDB with restore status

### 4. Event Processing
- **event_processor.py**: Handles regular file and meta.json uploads
  - Creates/updates DynamoDB records
  - Handles race conditions with conditional expressions
  - Retries with exponential backoff
- **restore_event_processor.py**: Updates metadata after Glacier restore
- **dlq_retry_processor.py**: Processes failed events from dead letter queues

## Data Model

### DynamoDB Schema (documents table)
```python
{
    "document_id": "01JGXXX...",  # ULID (partition key)
    "s3key": "01JGXXX.pdf",
    "file_name": "document.pdf",
    "original_file_name": "document.pdf",
    "s3bucket": "bucket-name",
    "meta_s3key": "01JGXXX.meta.json",
    "size": 12345,
    "content_type": "application/pdf",
    "updateddatetime": "2026-01-06T...",
    "has_metadata": "yes",
    # ... additional metadata fields from meta.json
}
```

## Development Practices

### Code Style
- Python 3.14 with type hints
- Google-style docstrings
- Black formatting (line length: 100)
- Ruff linting
- Comprehensive error handling with specific exceptions
- Structured logging (not print statements)

### Testing
- Unit tests with pytest
- AWS services mocked with moto
- Test coverage reporting
- Integration tests for E2E flows

### CI/CD
- **Pull Request Checks**: Run unit tests on every PR
- **Release Workflow**: 
  - Triggered on merge to main
  - Uses semantic-release for versioning
  - Follows Conventional Commits
  - Builds Lambda deployment package
  - Creates GitHub release with artifacts

### Versioning
- Semantic Versioning (SemVer)
- Conventional Commits:
  - `feat:` → minor version bump
  - `fix:` → patch version bump
  - `BREAKING CHANGE:` → major version bump

## Common Patterns

### 1. Lambda Handler Pattern
```python
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle Lambda invocation."""
    try:
        # Parse input
        # Validate
        # Process
        # Return response
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'result': 'success'})
        }
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
```

### 2. DynamoDB Operations
- Use `create_or_update_record()` from common.py
- Handle conditional check failures for race conditions
- Escape reserved words with ExpressionAttributeNames

### 3. S3 Operations
- Use pre-signed URLs for downloads (expires in 1 hour)
- Set Content-Disposition header for proper filename
- Handle archive status checks

### 4. Error Handling
- Specific exception types
- Retry with exponential backoff for transient failures
- Dead letter queues for persistent failures
- Structured error responses

## Environment Variables

All Lambda functions expect:
- `DOCUMENTS_TABLE`: DynamoDB table name
- `S3_BUCKET`: S3 bucket name
- `USERS_TABLE`: Users table name (for auth handlers)

Event processors also use:
- Various DLQ URLs for retry processing

## Known Issues & Considerations

1. **Race Conditions**: Handled with DynamoDB conditional expressions
2. **Large Files**: Use pre-signed URLs for uploads >= 10MB
3. **Glacier Restore**: Async process, client must poll for completion
4. **ULID vs UUID**: ULIDs are used for timestamp-based sorting
5. **Meta.json**: Required for all uploads, contains document metadata

## Future Improvements

See `.github/CODE_QUALITY_PLAN.md` for detailed improvement roadmap:
- Add type hints throughout
- Replace print() with logging
- Add linting/formatting to CI
- Improve test coverage reporting
- Add API documentation (OpenAPI/Swagger)
- Extract business logic from handlers

## Deployment

The release workflow creates a `lambda_function.zip` that can be deployed via Terraform or AWS CLI.

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup, coding standards, and submission guidelines.

## Security

- No hardcoded credentials
- Use IAM roles for AWS access
- Input validation on all endpoints
- Pre-signed URLs with expiration
- API authentication via API keys

## Support

For questions or issues:
1. Check existing documentation
2. Search closed issues
3. Open a new issue with detailed information

---

**Last Updated**: 2026-01-06
**Python Version**: 3.14
**AWS Region**: us-east-1 (configurable)
