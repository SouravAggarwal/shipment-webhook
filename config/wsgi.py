"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.
On AWS Lambda, auto-runs migrations and seeds vendor users on cold start
since /tmp/db.sqlite3 is ephemeral.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()


# Auto-migrate and seed on Lambda cold start
if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    from django.core.management import call_command
    from django.contrib.auth.models import User

    call_command("migrate", "--run-syncdb", verbosity=0)

    # Seed vendor users from environment (comma-separated user:pass pairs)
    vendor_creds = os.getenv("VENDOR_CREDENTIALS", "vendor_acme:securepass123")
    for cred in vendor_creds.split(","):
        if ":" in cred:
            username, password = cred.split(":", 1)
            if not User.objects.filter(username=username).exists():
                User.objects.create_user(username=username, password=password)
