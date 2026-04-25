"""Generic AWS SQS service for message queuing.

Reusable across multiple apps and services — accepts queue_url per call.
"""

import json
import logging
from typing import Any

import boto3
from django.conf import settings

logger = logging.getLogger(__name__)


class AWSSQSService:
    """Generic AWS SQS client. Queue URL is passed per operation."""

    def __init__(self):
        self._client = boto3.client(
            "sqs",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )

    def push_message(self, queue_url: str, body: dict[str, Any]) -> str:
        """Push a JSON message to the specified SQS queue.

        Returns the SQS MessageId.
        """
        response = self._client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(body),
        )
        message_id = response["MessageId"]
        logger.info("Pushed message to SQS %s (MessageId=%s)", queue_url, message_id)
        return message_id

    def receive_messages(
        self, queue_url: str, max_messages: int = 10, wait_seconds: int = 20,
    ) -> list[dict]:
        """Receive messages from the specified SQS queue (long-polling).

        Returns list of messages with 'MessageId', 'Body', 'ReceiptHandle'.
        """
        response = self._client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        return response.get("Messages", [])

    def delete_message(self, queue_url: str, receipt_handle: str) -> None:
        """Delete a processed message from the specified SQS queue."""
        self._client.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
        )
        logger.info("Deleted SQS message from %s", queue_url)
