CLASSIFICATION_PROMPT = """You are a strict JSON transformer for supply chain data.

Classify the input as: SHIPMENT, INVOICE, or UNCLASSIFIED.
Extract data into the matching schema. Use null for missing fields.
If unsure → UNCLASSIFIED. Do NOT hallucinate values.

Shipment schema: vendor_id, tracking_number, status (TRANSIT/DELIVERED/EXCEPTION), timestamp (ISO 8601)
Invoice schema: vendor_id, invoice_id, amount (number), currency (string)
Confidence: 0.0 to 1.0.
"""

STATUS_MAP = {
    "transit": "TRANSIT",
    "in_transit": "TRANSIT",
    "in transit": "TRANSIT",
    "shipping": "TRANSIT",
    "shipped": "TRANSIT",
    "delivered": "DELIVERED",
    "completed": "DELIVERED",
    "received": "DELIVERED",
    "exception": "EXCEPTION",
    "failed": "EXCEPTION",
    "returned": "EXCEPTION",
    "lost": "EXCEPTION",
    "delayed": "EXCEPTION",
}

VALID_SHIPMENT_STATUSES = ("TRANSIT", "DELIVERED", "EXCEPTION")
