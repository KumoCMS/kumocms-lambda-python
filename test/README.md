# Testing Guide

This directory contains unit tests for the Kumo CMS project.

## Setup

1. Install test dependencies:
```bash
pip install -r requirements-test.txt
```

## Running Tests

### Run all tests:
```bash
pytest
```

### Run with coverage:
```bash
pytest --cov=src --cov-report=html
```

### Run specific test file:
```bash
pytest test/unit/test_event_processor.py
```

### Run specific test class:
```bash
pytest test/unit/test_event_processor.py::TestHandleRegularFile
```

### Run specific test:
```bash
pytest test/unit/test_event_processor.py::TestHandleRegularFile::test_handle_regular_file_new_record
```

### Run tests with verbose output:
```bash
pytest -v
```

## Test Structure

- `unit/` - Directory containing unit tests
- `requirements-test.txt` - Testing dependencies (in root)

## Test Coverage

The tests cover:
- ✅ All functions in `event_processor.py`
- ✅ Happy path scenarios
- ✅ Error handling
- ✅ Edge cases
- ✅ Integration workflows
- ✅ Mocking of AWS services (S3, DynamoDB)

## Mocking Strategy

Tests use `unittest.mock` to mock:
- DynamoDB table operations
- S3 client operations  
- Environment variables
- External dependencies

This allows tests to run without actual AWS resources.