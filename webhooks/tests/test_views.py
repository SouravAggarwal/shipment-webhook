"""Tests for the webhook ingestion API."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from webhooks.models import RawWebhook, WebhookStatus


class WebhookIngestViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="vendor1", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.url = "/api/webhooks/ingest/"

    @patch("webhooks.views.AWSSQSService")
    def test_ingest_valid_payload(self, mock_sqs_cls):
        payload = {"tracking_number": "TRK123", "status": "delivered"}
        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "received")
        self.assertIn("webhook_id", response.data)

        webhook = RawWebhook.objects.get(id=response.data["webhook_id"])
        self.assertEqual(webhook.status, WebhookStatus.RECEIVED)
        self.assertEqual(webhook.vendor, self.user)
        mock_sqs_cls().push_message.assert_called_once()

    @patch("webhooks.views.AWSSQSService")
    def test_all_payloads_saved_as_received(self, mock_sqs_cls):
        """All payloads are saved with RECEIVED status (dedup happens in consumer)."""
        payload = {"tracking_number": "TRK123"}

        self.client.post(self.url, payload, format="json")
        self.client.post(self.url, payload, format="json")

        self.assertEqual(RawWebhook.objects.count(), 2)
        self.assertEqual(RawWebhook.objects.filter(status=WebhookStatus.RECEIVED).count(), 2)
        self.assertEqual(mock_sqs_cls().push_message.call_count, 2)

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {"data": "test"}, format="json")
        self.assertEqual(response.status_code, 401)

    @patch("webhooks.views.AWSSQSService")
    def test_invalid_payload_rejected(self, mock_sqs_cls):
        import json
        response = self.client.post(
            self.url, json.dumps("just a string"), content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("webhooks.views.AWSSQSService")
    def test_sqs_failure_still_saves_webhook(self, mock_sqs_cls):
        """Even if SQS push fails, the webhook is still saved."""
        mock_sqs_cls().push_message.side_effect = Exception("SQS down")
        payload = {"tracking_number": "TRK999"}

        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RawWebhook.objects.count(), 1)
