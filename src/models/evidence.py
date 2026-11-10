"""Evidence data model for preserving source traceability and preventing hallucinations."""

from datetime import datetime, timezone
import hashlib
from pydantic import BaseModel, Field

from src.models.enums import SourceType, VerificationStatus


def generate_evidence_id(company_id: str, field_name: str, source_url: str, value: str) -> str:
    """Create a deterministic unique ID for an evidence record."""
    raw = f"{company_id}:{field_name}:{source_url}:{value}".encode("utf-8")
    return f"ev_{hashlib.sha256(raw).hexdigest()[:12]}"


class Evidence(BaseModel):
    """Represents a verifiable piece of evidence backing an extracted company or contact field."""

    evidence_id: str = Field(..., description="Deterministic identifier for the evidence record")
    company_id: str = Field(..., description="ID of the company this evidence belongs to")
    field_name: str = Field(..., description="Name of the extracted field (e.g., managed_residential_units)")
    extracted_value: str = Field(..., description="String representation of the extracted value")
    source_url: str = Field(..., description="Exact URL where the supporting text was found")
    source_type: SourceType = Field(
        default=SourceType.COMPANY_HOMEPAGE,
        description="Category of the source document",
    )
    supporting_text: str = Field(
        ...,
        min_length=3,
        description="Verbatim quote or snippet from the source that proves the extracted value",
    )
    extraction_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the evidence was captured",
    )
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        description="Whether the supporting quote was verified against the fetched source text",
    )
