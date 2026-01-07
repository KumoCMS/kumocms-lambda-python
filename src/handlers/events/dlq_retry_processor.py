import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Literal, cast

import boto3

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialize AWS clients
sqs = boto3.client("sqs")
events = boto3.client("events")
dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")

# Environment variables
# We use .get() with defaults to avoid KeyErrors during initialization in local tests
EVENTBRIDGE_DLQ_OBJECT_CREATED_URL = os.environ.get("EVENTBRIDGE_DLQ_OBJECT_CREATED_URL", "")
EVENTBRIDGE_DLQ_OBJECT_RESTORED_URL = os.environ.get("EVENTBRIDGE_DLQ_OBJECT_RESTORED_URL", "")
LAMBDA_DLQ_EVENT_PROCESSOR_URL = os.environ.get("LAMBDA_DLQ_EVENT_PROCESSOR_URL", "")
LAMBDA_DLQ_RESTORE_PROCESSOR_URL = os.environ.get("LAMBDA_DLQ_RESTORE_PROCESSOR_URL", "")
MANUAL_CHECK_DLQ_URL = os.environ.get("MANUAL_CHECK_DLQ_URL", "")
EVENT_PROCESSOR_LAMBDA_ARN = os.environ.get("EVENT_PROCESSOR_LAMBDA_ARN", "")
RESTORE_EVENT_PROCESSOR_LAMBDA_ARN = os.environ.get("RESTORE_EVENT_PROCESSOR_LAMBDA_ARN", "")

MAX_RETRY_ATTEMPTS = 3


def get_retry_count(message: dict[str, Any]) -> int:
    """Extract retry count from message attributes.

    Args:
        message: SQS message dictionary.

    Returns:
        The retry count as an integer.
    """
    attributes = message.get("MessageAttributes", {})
    if "RetryCount" in attributes:
        return int(attributes["RetryCount"]["StringValue"])
    return 0


def send_to_manual_check(
    message_body: Any, error_message: str, source_queue: str, retry_count: int
) -> bool:
    """Send failed message to manual check DLQ with error details.

    Args:
        message_body: The original message payload.
        error_message: Description of why it failed.
        source_queue: Name of the queue the message came from.
        retry_count: Number of times it was retried.

    Returns:
        True if successfully sent, False otherwise.
    """
    try:
        enriched_message = {
            "original_message": message_body,
            "error": error_message,
            "source_queue": source_queue,
            "retry_count": retry_count,
            "failed_at": datetime.now(UTC).isoformat(),
            "requires_manual_review": True,
        }

        sqs.send_message(
            QueueUrl=MANUAL_CHECK_DLQ_URL,
            MessageBody=json.dumps(enriched_message),
            MessageAttributes={
                "SourceQueue": {"StringValue": source_queue, "DataType": "String"},
                "RetryCount": {"StringValue": str(retry_count), "DataType": "Number"},
                "ErrorType": {"StringValue": "MaxRetriesExceeded", "DataType": "String"},
            },
        )
        logger.info(f"Sent message to manual check DLQ after {retry_count} retries")
        return True
    except Exception as e:
        logger.error(f"Error sending to manual check DLQ: {e}")
        return False


def process_dlq_message(
    message: dict[str, Any],
    queue_url: str,
    target_lambda_arn: str,
    queue_name: str,
    is_sync: bool = False,
) -> dict[str, Any]:
    """Process messages from a DLQ by re-invoking the target Lambda.

    Args:
        message: SQS message.
        queue_url: Source DLQ URL.
        target_lambda_arn: ARN of the Lambda to re-invoke.
        queue_name: Human-readable name of the queue.
        is_sync: Whether to use synchronous invocation.

    Returns:
        Status dictionary.
    """
    try:
        body = json.loads(message["Body"])
        retry_count = get_retry_count(message)

        logger.info(f"Processing DLQ message from {queue_name}, retry count: {retry_count}")

        if retry_count >= MAX_RETRY_ATTEMPTS:
            logger.warning(f"Max retries exceeded for message from {queue_name}")
            send_to_manual_check(body, "Max retries exceeded", queue_name, retry_count)
            # Delete from DLQ since we've moved it to manual check
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
            return {"status": "moved_to_manual_check", "retry_count": retry_count}

        # Re-invoke the Lambda
        try:
            invocation_type: Literal["Event", "RequestResponse"] = (
                "RequestResponse" if is_sync else "Event"
            )
            response = lambda_client.invoke(
                FunctionName=target_lambda_arn,
                InvocationType=invocation_type,
                Payload=json.dumps(body),
            )

            if is_sync:
                response_payload = json.loads(response["Payload"].read())
                if response.get("FunctionError"):
                    raise Exception(f"Lambda invocation failed: {response_payload}")

            logger.info(f"Successfully re-invoked Lambda for {queue_name}")

            # Delete message from DLQ on successful retry
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
            return {"status": "retried", "retry_count": retry_count + 1}

        except Exception as e:
            logger.error(f"Error re-invoking Lambda for {queue_name}: {e}")
            new_retry_count = retry_count + 1

            if new_retry_count >= MAX_RETRY_ATTEMPTS:
                send_to_manual_check(body, str(e), queue_name, new_retry_count)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                return {"status": "moved_to_manual_check", "retry_count": new_retry_count}
            else:
                # Put back with incremented retry count
                sqs.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps(body),
                    MessageAttributes={
                        "RetryCount": {"StringValue": str(new_retry_count), "DataType": "Number"}
                    },
                )
                # Delete original message
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                return {"status": "retry_failed", "retry_count": new_retry_count}

    except Exception as e:
        logger.error(f"Error processing DLQ message: {e}")
        return {"status": "error", "error": str(e)}


def process_queue(
    queue_url: str, target_lambda_arn: str, queue_name: str, is_sync: bool
) -> dict[str, Any]:
    """Receive and process messages from a specific DLQ.

    Args:
        queue_url: SQS queue URL.
        target_lambda_arn: Lambda to re-invoke.
        queue_name: Queue name.
        is_sync: Whether to use synchronous invocation.

    Returns:
        Summary dictionary.
    """
    results: dict[str, Any] = {
        "queue_name": queue_name,
        "processed": 0,
        "retried": 0,
        "moved_to_manual": 0,
        "errors": 0,
    }

    if not queue_url:
        logger.warning(f"Queue URL for {queue_name} is empty, skipping.")
        return results

    try:
        # Receive messages from the queue (up to 10 at a time)
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            MessageAttributeNames=["All"],
            WaitTimeSeconds=5,
        )

        messages = response.get("Messages", [])
        logger.info(f"Received {len(messages)} messages from {queue_name}")

        for message in messages:
            results["processed"] += 1
            result = process_dlq_message(
                cast(dict[str, Any], message),
                queue_url,
                target_lambda_arn,
                queue_name,
                is_sync=is_sync,
            )

            if result["status"] == "retried":
                results["retried"] += 1
            elif result["status"] == "moved_to_manual_check":
                results["moved_to_manual"] += 1
            elif result["status"] == "error":
                results["errors"] += 1

    except Exception as e:
        logger.error(f"Error processing queue {queue_name}: {e}")
        results["errors"] += 1

    return results


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Retry processor Lambda - runs periodically.

    Processes messages from all DLQs and retries them.

    Args:
        event: CloudWatch Scheduled Event.
        context: Lambda context object.

    Returns:
        Summary of processing results.
    """
    logger.info("Starting DLQ retry processor")

    all_results: list[dict[str, Any]] = []

    # Map of queues and their targets
    queues_to_process = [
        (
            EVENTBRIDGE_DLQ_OBJECT_CREATED_URL,
            EVENT_PROCESSOR_LAMBDA_ARN,
            "EventBridge-ObjectCreated-DLQ",
            False,
        ),
        (
            EVENTBRIDGE_DLQ_OBJECT_RESTORED_URL,
            RESTORE_EVENT_PROCESSOR_LAMBDA_ARN,
            "EventBridge-ObjectRestored-DLQ",
            False,
        ),
        (
            LAMBDA_DLQ_EVENT_PROCESSOR_URL,
            EVENT_PROCESSOR_LAMBDA_ARN,
            "Lambda-EventProcessor-DLQ",
            True,
        ),
        (
            LAMBDA_DLQ_RESTORE_PROCESSOR_URL,
            RESTORE_EVENT_PROCESSOR_LAMBDA_ARN,
            "Lambda-RestoreProcessor-DLQ",
            True,
        ),
    ]

    for q_url, l_arn, q_name, sync in queues_to_process:
        results = process_queue(q_url, l_arn, q_name, sync)
        all_results.append(results)

    # Summary
    total_processed = sum(r["processed"] for r in all_results)
    total_retried = sum(r["retried"] for r in all_results)
    total_moved = sum(r["moved_to_manual"] for r in all_results)
    total_errors = sum(r["errors"] for r in all_results)

    logger.info(
        f"DLQ Retry Processor Summary: Processed={total_processed}, Retried={total_retried}, "
        f"MovedToManual={total_moved}, Errors={total_errors}"
    )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "DLQ retry processing completed",
                "summary": {
                    "total_processed": total_processed,
                    "total_retried": total_retried,
                    "total_moved_to_manual": total_moved,
                    "total_errors": total_errors,
                },
                "details": all_results,
            }
        ),
    }
