import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from webhooks.constants import STATUS_MAP, VALID_SHIPMENT_STATUSES


def canonical_json_hash(username: str, payload: dict[str, Any]) -> str:
    """Generate SHA-256 hash of username + canonicalized JSON payload."""
    canonical = username + ":" + json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_status(raw: Optional[str]) -> Optional[str]:
    """Normalize raw shipment status string to a valid ShipmentStatus value."""
    if not raw:
        return None
    upper = raw.strip().upper()
    if upper in VALID_SHIPMENT_STATUSES:
        return upper
    return STATUS_MAP.get(raw.strip().lower())


def parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string into a datetime object."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def parse_amount(raw) -> Optional[Decimal]:
    """Parse and validate a monetary amount. Returns None for invalid/negative values."""
    if raw is None:
        return None
    try:
        val = Decimal(str(raw))
        return val if val >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None
