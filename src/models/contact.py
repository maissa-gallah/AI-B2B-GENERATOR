"""Contact data model for decision-makers at property management companies."""

import hashlib
from typing import Optional
from pydantic import BaseModel, Field

from src.models.enums import EmailStatus


def generate_contact_id(company_id: str, full_name: str, position: str) -> str:
    """Create a deterministic unique ID for a contact person."""
    raw = f"{company_id}:{full_name.strip().lower()}:{position.strip().lower()}".encode("utf-8")
    return f"ct_{hashlib.sha256(raw).hexdigest()[:12]}"


class Contact(BaseModel):
    """Represents a publicly identified professional contact / decision-maker."""

    contact_id: str = Field(..., description="Unique deterministic contact identifier")
    company_id: str = Field(..., description="Associated company ID")
    company_name: str = Field(default="", description="Associated company name for easy readability")
    full_name: str = Field(..., min_length=2, description="Full name of the contact person")
    position: str = Field(
        ...,
        min_length=2,
        description="Job title/role (e.g., Geschäftsführer, Technischer Leiter, Head of Property Management)",
    )
    role_priority_tier: int = Field(
        default=3,
        ge=1,
        le=3,
        description="1 = Managing Director/GF, 2 = Technical/Operations/PM Head, 3 = Other staff",
    )
    professional_email: Optional[str] = Field(
        default=None,
        description="Publicly listed email address (never guessed or fabricated)",
    )
    is_generic_email: bool = Field(
        default=False,
        description="True if the email is a generic role address like info@ or kontakt@ rather than personal",
    )
    linkedin_url: Optional[str] = Field(
        default=None, description="Publicly available LinkedIn profile URL if found"
    )
    email_status: EmailStatus = Field(
        default=EmailStatus.NOT_FOUND,
        description="Strict verification status of the email address",
    )
    source_url: str = Field(..., description="Exact URL where this contact person was found")
    supporting_text: Optional[str] = Field(
        default=None, description="Verbatim snippet from Impressum or Team page confirming the contact"
    )
