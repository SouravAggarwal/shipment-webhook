"""Management command to run the SQS consumer."""

from django.core.management.base import BaseCommand

from webhooks.services.webhook_processor import WebhookProcessor


class Command(BaseCommand):
    help = "Run the SQS webhook consumer (long-polling loop)"

    def handle(self, *args, **options):
        self.stdout.write("Starting SQS webhook consumer...")
        WebhookProcessor().consume_from_sqs()
