import json
import logging
from django.conf import settings
from common.llm_service import LLMService
from common.sqs_service import AWSSQSService
from webhooks.constants import CLASSIFICATION_PROMPT
from webhooks.models import InvoiceRecord, RawWebhook, ShipmentUpdate, WebhookStatus
from webhooks.schemas import ClassificationEnum, WebhookClassification
from webhooks.utils import canonical_json_hash, normalize_status, parse_amount, parse_timestamp

logger = logging.getLogger(__name__)


class WebhookProcessor:
    """Classifies, validates, normalizes, and stores webhook payloads."""

    def __init__(self):
        self.threshold = settings.LLM_CONFIDENCE_THRESHOLD
        self.llm = LLMService()
        self.sqs = AWSSQSService()

    def process(self, webhook_id: int) -> None:
        """Process a single webhook: dedup check, classify, normalize, and store."""
        try:
            webhook = RawWebhook.objects.get(id=webhook_id)
        except RawWebhook.DoesNotExist:
            logger.error("Webhook %s not found", webhook_id)
            return

        if webhook.status != WebhookStatus.RECEIVED:
            logger.info("Webhook %s status is %s, skipping", webhook_id, webhook.status)
            return

        # Deduplication: check if an earlier webhook with same hash was already processed
        if self._is_duplicate(webhook):
            self._update_status(webhook, WebhookStatus.DUPLICATE)
            logger.info("Webhook %s is a duplicate, skipping", webhook_id)
            return

        self._update_status(webhook, WebhookStatus.PROCESSING)

        try:
            result = self._classify(webhook.payload)
            
            if result.confidence < self.threshold or result.classification == ClassificationEnum.UNCLASSIFIED:
                self._update_status(webhook, WebhookStatus.UNCLASSIFIED)
                return

            if result.classification == ClassificationEnum.SHIPMENT and result.shipment_data:
                self._store_shipment(webhook, result.shipment_data)
            elif result.classification == ClassificationEnum.INVOICE and result.invoice_data:
                self._store_invoice(webhook, result.invoice_data)
            else:
                self._update_status(webhook, WebhookStatus.UNCLASSIFIED)

        except Exception:
            logger.exception("Failed to process webhook %s", webhook_id)
            self._update_status(webhook, WebhookStatus.FAILED)
            raise

    def consume_from_sqs(self) -> None:
        """Long-polling SQS"""
        queue_url = settings.SQS_QUEUE_URL
        logger.info("Starting SQS consumer on %s...", queue_url)

        while True:
            messages = self.sqs.receive_messages(queue_url, max_messages=10, wait_seconds=20)
            for msg in messages:
                try:
                    body = json.loads(msg["Body"])
                    webhook_id = body["webhook_id"]
                    logger.info("Processing webhook %s from SQS", webhook_id)
                    self.process(webhook_id)
                    self.sqs.delete_message(queue_url, msg["ReceiptHandle"])
                except Exception:
                    logger.exception("Failed to process SQS message: %s", msg.get("MessageId"))


    def _is_duplicate(self, webhook: RawWebhook) -> bool:
        payload_hash = canonical_json_hash(webhook.vendor.username, webhook.payload)
        webhook.payload_hash = payload_hash
        webhook.save(update_fields=["payload_hash", "updated_at"])

        return RawWebhook.objects.filter(
            vendor=webhook.vendor,
            payload_hash=payload_hash,
            status__in=[
                WebhookStatus.PROCESSED,
                WebhookStatus.PROCESSING,
                WebhookStatus.DUPLICATE,
            ],
        ).exclude(id=webhook.id).exists()

    def _classify(self, payload: dict) -> WebhookClassification:
        return self.llm.classify(
            prompt=CLASSIFICATION_PROMPT,
            user_input=f"Webhook payload:\n{payload}",
            output_schema=WebhookClassification,
        )

    @staticmethod
    def _update_status(webhook: RawWebhook, new_status: str) -> None:
        webhook.status = new_status
        webhook.save(update_fields=["status", "updated_at"])

    def _store_shipment(self, webhook, data) -> None:
        status = normalize_status(data.status)
        timestamp = parse_timestamp(data.timestamp)

        if not data.tracking_number or not status or not timestamp:
            self._update_status(webhook, WebhookStatus.FAILED)
            return

        ShipmentUpdate.objects.create(
            vendor=webhook.vendor, raw_webhook=webhook,
            tracking_number=data.tracking_number, status=status, timestamp=timestamp,
        )
        self._update_status(webhook, WebhookStatus.PROCESSED)

    def _store_invoice(self, webhook, data) -> None:
        amount = parse_amount(data.amount)

        if not data.invoice_id or amount is None or not data.currency:
            self._update_status(webhook, WebhookStatus.FAILED)
            return

        InvoiceRecord.objects.create(
            vendor=webhook.vendor, raw_webhook=webhook,
            invoice_id=data.invoice_id, amount=amount, currency=data.currency.upper().strip(),
        )
        self._update_status(webhook, WebhookStatus.PROCESSED)
