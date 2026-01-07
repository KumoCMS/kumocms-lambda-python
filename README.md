# Kumo CMS Lambda Functions

![Version](https://img.shields.io/github/v/release/KumoCMS/kumocms-lambda-python)
![Build Status](https://img.shields.io/github/actions/workflow/status/KumoCMS/kumocms-lambda-python/check_pull_request.yml?branch=main)

This repository contains the AWS Lambda functions and associated code for the Kumo Content Management System (CMS) project.

## 🚀 Overview

The project provides a set of serverless API handlers and event processors to manage document uploads, retrieval, archiving, and restoration. It is built using Python 3.14 and deployed on AWS Lambda.

## 📂 Project Structure

- `src/`: Contains the core logic for the Lambda functions.
  - `handlers/api/`: Specific handlers for different API endpoints (Upload, Download, Search, etc.).
  - `handlers/events/`: Logic for processing S3/EventBridge events.
  - `common/`: Shared utilities and common code.
- `test/unit/`: unit test suite.
- `.github/workflows/`: CI/CD pipelines including automated testing and versioned releases.
- `requirements.txt`: Lambda function dependencies.
- `requirements-test.txt`: Testing dependencies.
- `package.json`: Configuration for semantic-release.

## 🛠 Setup & Development

### Prerequisites

- Python 3.14
- Node.js (for Semantic Release)
- `pip` for dependency management

### Local Installation

1. Clone the repository:
   ```bash
   git clone git@github.com:KumoCMS/kumocms-lambda-python.git
   cd kumocms-lambda-python
   ```

2. Install dependencies for the Lambda functions:
   ```bash
   pip install -r requirements.txt
   ```

3. Install testing dependencies:
   ```bash
   pip install -r requirements-test.txt
   ```

## 🧪 Testing

We use `pytest` for unit testing. All handlers and processors are mocked using `unittest.mock` to allow for rapid local development without requiring AWS resources.

To run all tests:
```bash
pytest
```

For more detailed testing instructions, see the [`test/README.md`](test/README.md).

## 📦 CI/CD & Releases

The project uses **Semantic Release** to automate versioning and GitHub Releases.

### Workflows

- **Check Pull Request**: Runs unit tests on every pull request and push to non-main branches.
- **Release**: Automatically triggered when a PR is merged into the `main` branch. It:
  1. Validates the code (runs unit tests).
  2. Increments the version based on [Conventional Commits](https://www.conventionalcommits.org/).
  3. Generates a `CHANGELOG.md`.
  4. Builds a Lambda-ready production zip package (`lambda_function.zip`).
  5. Publishes a new GitHub Release with the build asset.

### Conventional Commits

We follow the Conventional Commits specification for automatic versioning:
- `fix:` -> Patch release (e.g., v1.0.1)
- `feat:` -> Minor release (e.g., v1.1.0)
- `feat!:` or `BREAKING CHANGE:` -> Major release (e.g., v2.0.0)

## 📄 License

Internal KumoCMS project.
