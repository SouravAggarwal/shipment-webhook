from django.contrib import admin

from webhooks.models import InvoiceRecord, RawWebhook, ShipmentUpdate


@admin.register(RawWebhook)
class RawWebhookAdmin(admin.ModelAdmin):
    list_display = ["id", "vendor", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["payload_hash"]
    readonly_fields = ["id", "payload", "payload_hash", "created_at", "updated_at"]


@admin.register(ShipmentUpdate)
class ShipmentUpdateAdmin(admin.ModelAdmin):
    list_display = ["id", "vendor", "tracking_number", "status", "timestamp"]
    list_filter = ["status"]


@admin.register(InvoiceRecord)
class InvoiceRecordAdmin(admin.ModelAdmin):
    list_display = ["id", "vendor", "invoice_id", "amount", "currency"]
