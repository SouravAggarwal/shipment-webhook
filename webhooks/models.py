from django.conf import settings
from django.db import models


class WebhookStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    DUPLICATE = "DUPLICATE", "Duplicate"
    PROCESSING = "PROCESSING", "Processing"
    PROCESSED = "PROCESSED", "Processed"
    UNCLASSIFIED = "UNCLASSIFIED", "Unclassified"
    FAILED = "FAILED", "Failed"


class ShipmentStatus(models.TextChoices):
    TRANSIT = "TRANSIT", "In Transit"
    DELIVERED = "DELIVERED", "Delivered"
    EXCEPTION = "EXCEPTION", "Exception"


class RawWebhook(models.Model):
    """Stores all webhook events including duplicates."""

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="webhooks",
    )
    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=20, choices=WebhookStatus.choices, default=WebhookStatus.RECEIVED,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Webhook {self.id} [{self.status}]"


class ShipmentUpdate(models.Model):
    """Normalized shipment update record."""

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shipments",
    )
    raw_webhook = models.ForeignKey(RawWebhook, on_delete=models.CASCADE, related_name="shipments")
    tracking_number = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=ShipmentStatus.choices)
    timestamp = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Shipment {self.tracking_number} [{self.status}]"


class InvoiceRecord(models.Model):
    """Normalized invoice record."""

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="invoices",
    )
    raw_webhook = models.ForeignKey(RawWebhook, on_delete=models.CASCADE, related_name="invoices")
    invoice_id = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Invoice {self.invoice_id} [{self.amount} {self.currency}]"
