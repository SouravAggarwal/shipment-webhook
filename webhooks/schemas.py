from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ClassificationEnum(str, Enum):
    SHIPMENT = "SHIPMENT"
    INVOICE = "INVOICE"
    UNCLASSIFIED = "UNCLASSIFIED"


class ShipmentData(BaseModel):
    """Extracted shipment data from webhook payload."""

    vendor_id: Optional[str] = Field(
        None, description="Vendor identifier from the payload"
    )
    tracking_number: Optional[str] = Field(
        None, description="Shipment tracking number"
    )
    status: Optional[str] = Field(
        None,
        description="Shipment status: TRANSIT, DELIVERED, or EXCEPTION",
    )
    timestamp: Optional[str] = Field(
        None, description="Event timestamp in ISO 8601 format"
    )


class InvoiceData(BaseModel):
    """Extracted invoice data from webhook payload."""

    vendor_id: Optional[str] = Field(
        None, description="Vendor identifier from the payload"
    )
    invoice_id: Optional[str] = Field(
        None, description="Invoice identifier"
    )
    amount: Optional[float] = Field(
        None, description="Invoice amount as a number"
    )
    currency: Optional[str] = Field(
        None, description="Currency code (e.g., USD, EUR)"
    )


class WebhookClassification(BaseModel):
    """LLM structured output for webhook classification and extraction."""

    classification: ClassificationEnum = Field(
        description="Type of webhook event: SHIPMENT, INVOICE, or UNCLASSIFIED"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence score from 0.0 to 1.0",
    )
    shipment_data: Optional[ShipmentData] = Field(
        None,
        description="Extracted shipment data. Only populated when classification is SHIPMENT.",
    )
    invoice_data: Optional[InvoiceData] = Field(
        None,
        description="Extracted invoice data. Only populated when classification is INVOICE.",
    )
