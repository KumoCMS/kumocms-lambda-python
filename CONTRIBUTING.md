# Contributing to Kumo CMS Lambda Functions

Thank you for your interest in contributing to the Kumo Content Management System Lambda Functions! We welcome contributions from the community.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Reporting Bugs](#reporting-bugs)
- [Feature Requests](#feature-requests)

## Code of Conduct

This project adheres to a Code of Conduct that all contributors are expected to follow. Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before contributing.

## Getting Started

### Prerequisites

- Python 3.14+
- Node.js 18+ (for semantic-release)
- AWS CLI configured (for deployment)
- Git

### Setting Up Your Development Environment

1. **Fork the repository** on GitHub

2. **Clone your fork**:
   ```bash
   git clone git@github.com:YOUR_USERNAME/kumocms-lambda-python.git
   cd kumocms-lambda-python
   ```

3. **Add upstream remote**:
   ```bash
   git remote add upstream git@github.com:KumoCMS/kumocms-lambda-python.git
   ```

4. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

5. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-test.txt
   ```

6. **Install development tools**:
   ```bash
   pip install ruff black mypy
   ```

## Development Workflow

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following our [coding standards](#coding-standards)

3. **Run tests**:
   ```bash
   pytest
   ```

4. **Run linting and formatting**:
   ```bash
   ruff check .
   black .
   mypy src/
   ```

5. **Commit your changes** using [Conventional Commits](https://www.conventionalcommits.org/):
   ```bash
   git commit -m "feat: add new feature"
   ```

   Commit types:
   - `feat:` - New feature (minor version bump)
   - `fix:` - Bug fix (patch version bump)
   - `docs:` - Documentation changes
   - `style:` - Code style changes (formatting, etc.)
   - `refactor:` - Code refactoring
   - `test:` - Adding or updating tests
   - `chore:` - Maintenance tasks
   - `BREAKING CHANGE:` - Breaking changes (major version bump)

6. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Open a Pull Request** on GitHub

## Coding Standards

### Python Style Guide

- Follow [PEP 8](https://pep8.org/) style guide
- Use [Black](https://black.readthedocs.io/) for code formatting (line length: 100)
- Use [Ruff](https://docs.astral.sh/ruff/) for linting
- Use type hints for all function signatures
- Write comprehensive docstrings (Google style)

### Example:

```python
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

def process_document(
    document_id: str,
    metadata: Dict[str, Any],
    validate: bool = True
) -> Dict[str, Any]:
    """
    Process a document with the given metadata.
    
    Args:
        document_id: Unique identifier for the document
        metadata: Document metadata dictionary
        validate: Whether to validate metadata before processing
        
    Returns:
        Dictionary containing processing results
        
    Raises:
        ValueError: If document_id is invalid
        ValidationError: If metadata validation fails
    """
    logger.info(f"Processing document: {document_id}")
    # Implementation here
    return {"status": "success", "document_id": document_id}
```

### Code Organization

- Keep functions small and focused (single responsibility)
- Extract business logic from Lambda handlers
- Use meaningful variable and function names
- Avoid magic numbers - use named constants
- Handle errors specifically, not with generic `except Exception`

### Logging

- Use Python's `logging` module, not `print()`
- Log at appropriate levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Include context in log messages

```python
import logging

logger = logging.getLogger(__name__)

logger.info(f"Processing document {document_id}")
logger.error(f"Failed to upload document {document_id}: {error}")
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest test/unit/test_upload.py

# Run with verbose output
pytest -v
```

### Writing Tests

- Write unit tests for all new functions
- Use mocking for AWS services (boto3)
- Aim for >80% code coverage
- Test edge cases and error conditions
- Use descriptive test names

```python
def test_upload_document_with_valid_metadata():
    """Test that document upload succeeds with valid metadata."""
    # Arrange
    document_id = "test-doc-123"
    metadata = {"title": "Test Document"}
    
    # Act
    result = upload_document(document_id, metadata)
    
    # Assert
    assert result["status"] == "success"
    assert result["document_id"] == document_id
```

## Submitting Changes

### Pull Request Process

1. **Update documentation** if you've changed APIs or added features
2. **Add tests** for new functionality
3. **Ensure all tests pass** and coverage is maintained
4. **Update CHANGELOG.md** if making significant changes (semantic-release will handle this)
5. **Request review** from maintainers
6. **Address feedback** promptly

### Pull Request Checklist

- [ ] Code follows the project's coding standards
- [ ] All tests pass locally
- [ ] New tests added for new functionality
- [ ] Documentation updated (if applicable)
- [ ] Commit messages follow Conventional Commits
- [ ] No merge conflicts with main branch
- [ ] Code has been formatted with Black
- [ ] Linting passes with Ruff
- [ ] Type checking passes with mypy

## Reporting Bugs

### Before Submitting a Bug Report

- Check existing issues to avoid duplicates
- Collect relevant information (logs, error messages, environment details)
- Try to reproduce the issue with the latest version

### How to Submit a Bug Report

Create an issue on GitHub with the following information:

**Title**: Brief, descriptive summary

**Description**:
- **Expected behavior**: What should happen
- **Actual behavior**: What actually happens
- **Steps to reproduce**: Detailed steps to reproduce the issue
- **Environment**: Python version, OS, AWS region, etc.
- **Logs**: Relevant error messages or stack traces
- **Screenshots**: If applicable

## Feature Requests

We welcome feature requests! Please create an issue with:

- **Use case**: Why is this feature needed?
- **Proposed solution**: How should it work?
- **Alternatives considered**: Other approaches you've thought about
- **Additional context**: Any other relevant information

## Questions?

If you have questions about contributing, please:

1. Check existing documentation
2. Search closed issues
3. Open a new issue with the `question` label

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Recognition

Contributors will be recognized in our release notes and CHANGELOG.md.

Thank you for contributing to Kumo CMS Lambda Functions! 🎉
