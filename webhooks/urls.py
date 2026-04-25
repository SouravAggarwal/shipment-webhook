from django.urls import path

from webhooks.views import WebhookIngestView

urlpatterns = [
    path("webhooks/ingest/", WebhookIngestView.as_view(), name="webhook-ingest"),
]
