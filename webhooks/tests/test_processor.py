"""Tests for the WebhookProcessor business logic."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from webhooks.models import InvoiceRecord, RawWebhook, ShipmentUpdate, WebhookStatus
from webhooks.schemas import (
    ClassificationEnum,
    InvoiceData,
    ShipmentData,
    WebhookClassification,
)
from webhooks.services.webhook_processor import WebhookProcessor
from webhooks.utils import normalize_status, parse_amount, parse_timestamp


class NormalizeStatusTest(TestCase):
    def test_valid_statuses(self):
        self.assertEqual(normalize_status("TRANSIT"), "TRANSIT")
        self.assertEqual(normalize_status("DELIVERED"), "DELIVERED")
        self.assertEqual(normalize_status("EXCEPTION"), "EXCEPTION")

    def test_variant_mappings(self):
        self.assertEqual(normalize_status("in_transit"), "TRANSIT")
        self.assertEqual(normalize_status("shipped"), "TRANSIT")
        self.assertEqual(normalize_status("completed"), "DELIVERED")
        self.assertEqual(normalize_status("failed"), "EXCEPTION")

    def test_none_and_unknown(self):
        self.assertIsNone(normalize_status(None))
        self.assertIsNone(normalize_status("UNKNOWN"))


class ParseTimestampTest(TestCase):
    def test_valid_iso(self):
        ts = parse_timestamp("2024-01-15T10:30:00Z")
        self.assertIsInstance(ts, datetime)

    def test_invalid(self):
        self.assertIsNone(parse_timestamp("not-a-date"))
        self.assertIsNone(parse_timestamp(None))


class ParseAmountTest(TestCase):
    def test_valid(self):
        self.assertEqual(parse_amount(100.50), Decimal("100.50"))
        self.assertEqual(parse_amount("99.99"), Decimal("99.99"))

    def test_invalid(self):
        self.assertIsNone(parse_amount(-50))
        self.assertIsNone(parse_amount("abc"))
        self.assertIsNone(parse_amount(None))


class ProcessWebhookTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="vendor1", password="pass")
        self.processor = WebhookProcessor()

    def _create_webhook(self, payload=None, status=WebhookStatus.RECEIVED):
        return RawWebhook.objects.create(
            vendor=self.user,
            payload=payload or {"test": True},
            payload_hash="",
            status=status,
        )

    @patch.object(WebhookProcessor, "_classify")
    def test_process_shipment(self, mock_classify):
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
    def test_process_invoice(self, mock_classify):
        mock_classify.return_value = WebhookClassification(
            classification=ClassificationEnum.INVOICE, confidence=0.9,
            invoice_data=InvoiceData(
                invoice_id="INV-001", amount=1500.50, currency="USD",
            ),
        )
        webhook = self._create_webhook()
        self.processor.process(webhook.id)

        webhook.refresh_from_db()
        self.assertEqual(webhook.status, WebhookStatus.PROCESSED)
        self.assertEqual(InvoiceRecord.objects.count(), 1)

    @patch.object(WebhookProcessor, "_classify")
    def test_low_confidence_marks_unclassified(self, mock_classify):
        mock_classify.return_value = WebhookClassification(
            classification=ClassificationEnum.SHIPMENT, confidence=0.3,
            shipment_data=ShipmentData(tracking_number="TRK-001"),
        )
        webhook = self._create_webhook()
        self.processor.process(webhook.id)

        webhook.refresh_from_db()
        self.assertEqual(webhook.status, WebhookStatus.UNCLASSIFIED)
        self.assertEqual(ShipmentUpdate.objects.count(), 0)

    @override_settings(LLM_CONFIDENCE_THRESHOLD=0.7)
    @patch.object(WebhookProcessor, "_classify")
    def test_confidence_threshold_from_settings(self, mock_classify):
        mock_classify.return_value = WebhookClassification(
            classification=ClassificationEnum.SHIPMENT, confidence=0.4,
            shipment_data=ShipmentData(tracking_number="TRK-001"),
        )
        webhook = self._create_webhook()
        processor = WebhookProcessor()
        processor.process(webhook.id)

        webhook.refresh_from_db()
        self.assertEqual(webhook.status, WebhookStatus.UNCLASSIFIED)

    @patch.object(WebhookProcessor, "_classify")
    def test_invalid_shipment_data_marks_failed(self, mock_classify):
        mock_classify.return_value = WebhookClassification(
            classification=ClassificationEnum.SHIPMENT, confidence=0.9,
            shipment_data=ShipmentData(),
        )
        webhook = self._create_webhook()
        self.processor.process(webhook.id)

        webhook.refresh_from_db()
        self.assertEqual(webhook.status, WebhookStatus.FAILED)

    @patch.object(WebhookProcessor, "_classify")
    def test_llm_exception_marks_failed(self, mock_classify):
        mock_classify.side_effect = Exception("LLM timeout")
        webhook = self._create_webhook()

        with self.assertRaises(Exception):
            self.processor.process(webhook.id)

        webhook.refresh_from_db()
        self.assertEqual(webhook.status, WebhookStatus.FAILED)

    def test_skip_non_received(self):
        webhook = self._create_webhook(status=WebhookStatus.PROCESSING)
        self.processor.process(webhook.id)
        webhook.refresh_from_db()
        self.assertEqual(webhook.status, WebhookStatus.PROCESSING)

    def test_nonexistent_webhook(self):
        self.processor.process(999999)

    @patch.object(WebhookProcessor, "_classify")
    def test_duplicate_detected_and_marked(self, mock_classify):
        """If an earlier webhook with same hash was processed, new one is marked DUPLICATE."""
        payload = {"tracking_number": "TRK-001", "status": "delivered"}

        # First webhook — already processed
        first = self._create_webhook(payload=payload, status=WebhookStatus.RECEIVED)
        mock_classify.return_value = WebhookClassification(
            classification=ClassificationEnum.SHIPMENT, confidence=0.95,
            shipment_data=ShipmentData(
                tracking_number="TRK-001", status="DELIVERED",
                timestamp="2024-01-15T10:00:00Z",
            ),
        )
        self.processor.process(first.id)
        first.refresh_from_db()
        self.assertEqual(first.status, WebhookStatus.PROCESSED)

        # Second webhook — same payload, should be marked as DUPLICATE
        second = self._create_webhook(payload=payload, status=WebhookStatus.RECEIVED)
        self.processor.process(second.id)
        second.refresh_from_db()
        self.assertEqual(second.status, WebhookStatus.DUPLICATE)
        # LLM should NOT have been called for the duplicate
        self.assertEqual(mock_classify.call_count, 1)

    @patch.object(WebhookProcessor, "_classify")
    def test_same_payload_different_vendors_not_duplicate(self, mock_classify):
        """Same payload from different vendors should NOT be duplicate."""
        user2 = User.objects.create_user(username="vendor2", password="pass")
        payload = {"tracking_number": "TRK-001"}

        mock_classify.return_value = WebhookClassification(
            classification=ClassificationEnum.UNCLASSIFIED, confidence=0.3,
        )

        first = RawWebhook.objects.create(
            vendor=self.user, payload=payload, payload_hash="", status=WebhookStatus.RECEIVED,
        )
        self.processor.process(first.id)
        first.refresh_from_db()
        self.assertEqual(first.status, WebhookStatus.UNCLASSIFIED)

        second = RawWebhook.objects.create(
            vendor=user2, payload=payload, payload_hash="", status=WebhookStatus.RECEIVED,
        )
        self.processor.process(second.id)
        second.refresh_from_db()
        # Different vendor → not duplicate, should also be UNCLASSIFIED (not DUPLICATE)
        self.assertNotEqual(second.status, WebhookStatus.DUPLICATE)
