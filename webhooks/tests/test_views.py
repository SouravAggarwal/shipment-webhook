"""Tests for the webhook ingestion API."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from webhooks.models import RawWebhook, WebhookStatus


class TestWebhookIngestAPI(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="vendor1", password="pass")
        self.client.force_authenticate(user=self.user)
        self.url = "/api/webhooks/ingest/"

    @patch("webhooks.views.AWSSQSService")
    def test_valid_payload_saved_and_queued(self, mock_sqs_cls):
        response = self.client.post(
            self.url, {"tracking_number": "TRK-001", "status": "delivered"}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("webhook_id", response.data)

        webhook = RawWebhook.objects.get(id=response.data["webhook_id"])
        self.assertEqual(webhook.status, WebhookStatus.RECEIVED)
        self.assertEqual(webhook.vendor, self.user)
        mock_sqs_cls().push_message.assert_called_once()

    def test_unauthenticated_request_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {"data": "test"}, format="json")
        self.assertEqual(response.status_code, 401)
