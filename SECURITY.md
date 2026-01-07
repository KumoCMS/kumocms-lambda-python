# Security Policy

## Supported Versions

We only provide security updates for the latest major version of this project.

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |
| < 1.0.0 | :x:                |

## Reporting a Vulnerability

We take the security of our project seriously. If you believe you have found a security vulnerability, please report it to us responsibly.

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to [security@kumocms.example.com].

Please include the following in your report:
- A description of the vulnerability.
- Steps to reproduce the issue.
- Potential impact of the vulnerability.
- Any suggested fixes or mitigations.

We will acknowledge receipt of your report within 48 hours and provide a timeline for a fix within 5 business days.

## Security Practices

This project follows these security practices:
- **No Hardcoded Secrets**: We use environment variables and AWS Secrets Manager for sensitive information.
- **Least Privilege**: IAM roles are scoped to the minimum permissions required.
- **Input Validation**: All API inputs are validated before processing.
- **Dependency Scanning**: We use automated tools to scan for vulnerable dependencies.
- **Encryption**: Data is encrypted at rest in S3 and DynamoDB, and in transit via HTTPS/TLS.
