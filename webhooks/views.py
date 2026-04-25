import logging
from django.conf import settings
from rest_framework import status
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from webhooks.utils import canonical_json_hash
from common.sqs_service import AWSSQSService
from webhooks.models import RawWebhook, WebhookStatus

logger = logging.getLogger(__name__)


class WebhookIngestView(APIView):
    """POST /api/webhooks/ingest/

    Accepts any JSON payload, persists it, and pushes to SQS for async processing.
    Returns 200 immediately. Deduplication is handled by the consumer.
    """

    authentication_classes = [BasicAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        payload = request.data
        if not isinstance(payload, dict):
            return Response(
                {"error": "Payload must be a JSON object"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        webhook = RawWebhook.objects.create(
            vendor=request.user,
            payload=payload,
            payload_hash=canonical_json_hash(request.user.username, payload),
            status=WebhookStatus.RECEIVED,
        )

        try:
            sqs = AWSSQSService()
            sqs.push_message(settings.SQS_QUEUE_URL, {"webhook_id": str(webhook.id)})
        except Exception:
            logger.exception("Failed to push webhook %s to SQS", webhook.id)

        logger.info("Webhook %s from %s ingested", webhook.id, request.user.username)
        return Response(
            {"status": "received", "webhook_id": str(webhook.id)},
            status=status.HTTP_200_OK,
        )
