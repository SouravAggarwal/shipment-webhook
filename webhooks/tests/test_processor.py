"""Tests for the WebhookProcessor business logic."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from webhooks.models import RawWebhook, ShipmentUpdate, WebhookStatus
from webhooks.schemas import ClassificationEnum, ShipmentData, WebhookClassification
from webhooks.services.webhook_processor import WebhookProcessor


class TestWebhookProcessor(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="vendor1", password="pass")
        self.processor = WebhookProcessor()

    def _create_webhook(self, payload=None, status=WebhookStatus.RECEIVED):
        return RawWebhook.objects.create(
            vendor=self.user, payload=payload or {"tracking_number": "TRK-001"},
            payload_hash="", status=status,
        )

    @patch.object(WebhookProcessor, "_classify")
    def test_shipment_classified_and_stored(self, mock_classify):
        mock_classify.return_value = WebhookClassification(
            classification=ClassificationEnum.SHIPMENT, confidence=0.95,
            shipment_data=ShipmentData(
                tracking_number="TRK-001", status="DELIVERED",
                timestamp="2024-01-15T10:00:00Z",
            ),
        )
        webhook = self._create_webhook()
        self.processor.process(webhook.id)

        webhook.refresh_from_db()
        self.assertEqual(webhook.status, WebhookStatus.PROCESSED)
        self.assertEqual(ShipmentUpdate.objects.count(), 1)
        self.assertEqual(ShipmentUpdate.objects.first().tracking_number, "TRK-001")

    @patch.object(WebhookProcessor, "_classify")
    def test_duplicate_detected_and_skipped(self, mock_classify):
        mock_classify.return_value = WebhookClassification(
            classification=ClassificationEnum.SHIPMENT, confidence=0.95,
            shipment_data=ShipmentData(
                tracking_number="TRK-001", status="DELIVERED",
                timestamp="2024-01-15T10:00:00Z",
            ),
        )
        payload = {"tracking_number": "TRK-001", "status": "delivered"}

        first = self._create_webhook(payload=payload)
        self.processor.process(first.id)

        second = self._create_webhook(payload=payload)
        self.processor.process(second.id)

        second.refresh_from_db()
        self.assertEqual(second.status, WebhookStatus.DUPLICATE)
        self.assertEqual(mock_classify.call_count, 1)
