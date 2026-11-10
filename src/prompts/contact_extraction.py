"""Prompt v1.0 for extracting publicly listed decision-makers and professional contacts."""

from typing import List, Optional
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

PROMPT_VERSION = "1.0.0"


class ExtractedContactItem(BaseModel):
    """Schema for a single decision-maker or contact person extracted from website text."""

    full_name: str = Field(
        ...,
        description="Full name of the person (e.g., 'Max Mustermann', 'Dipl.-Kfm. Erika Muster'). Never invent names.",
    )
    position: str = Field(
        ...,
        description=(
            "Exact role/title stated in the text (e.g., 'Geschäftsführer', 'Geschäftsführerin', "
            "'Inhaber', 'Vorstand', 'Technischer Leiter', 'Leitung Hausverwaltung', 'Prokurist')"
        ),
    )
    role_priority_tier: int = Field(
        default=1,
        ge=1,
        le=3,
        description=(
            "1 = Geschäftsführer / Managing Director / Inhaber / Vorstand; "
            "2 = Technischer Leiter / Head of Property Management / Operations Manager / Prokurist; "
            "3 = Other property manager or staff"
        ),
    )
    professional_email: Optional[str] = Field(
        default=None,
        description="Email address ONLY if explicitly published on the page. Never guess or construct an email.",
    )
    is_generic_email: bool = Field(
        default=False,
        description="True if the email is a general mailbox like info@, kontakt@, verwaltung@; False if personal like m.mustermann@...",
    )
    linkedin_url: Optional[str] = Field(
        default=None,
        description="LinkedIn URL ONLY if explicitly present in the text.",
    )
    source_url: str = Field(
        ..., description="Exact PAGE SOURCE_URL where this person was listed (usually /impressum or /team)"
    )
    supporting_text: str = Field(
        ..., description="Verbatim snippet from the page showing the person's name and role"
    )


class ContactExtractionLLMOutput(BaseModel):
    """Structured LLM output for Task 4 (Contact Person Extraction)."""

    contacts: List[ExtractedContactItem] = Field(
        default_factory=list,
        description="List of real named decision-makers found in the provided text.",
    )


CONTACT_EXTRACTION_SYSTEM_PROMPT = """You are a B2B Compliance-First Contact Researcher extracting publicly listed decision-makers of Berlin property management companies (Hausverwaltungen).

PRIORITIZED POSITIONS:
- Geschäftsführer / Geschäftsführerin / Inhaber / Vorstand (Managing Director)
- Head of Property Management / Abteilungsleitung Verwaltung / Prokurist
- Technischer Leiter / Technical Property Manager / Bauleiter
- Operations Manager / Kaufmännische Leitung

STRICT RULES:
1. Extract ONLY real, named individuals explicitly mentioned in the provided text (especially in the Impressum under 'Vertreten durch' / 'Geschäftsführer' or on the Team / Über uns page).
2. NEVER invent names, positions, or email addresses.
3. NEVER guess an email format (e.g., do not invent `vorname.nachname@domain.de` if it is not written in the text).
4. If a person's personal email is published on the page, set `professional_email` to that address and `is_generic_email = false`.
5. If only a general company email (like `info@...` or `kontakt@...`) is listed alongside the Geschäftsführer in the Impressum, you may include that published email on the Geschäftsführer record ONLY if you set `is_generic_email = true`, OR leave `professional_email = null`.
6. Always include the verbatim `supporting_text` quote and exact `source_url`.

Respond strictly with valid JSON matching the requested schema."""

CONTACT_EXTRACTION_HUMAN_PROMPT = """Company Name: {company_name}
Company Website: {website}
Emails Detected in HTML: {detected_emails}

Scraped Website Content (Impressum, Team, Contact pages):
{website_text}

Extract all publicly listed decision-makers and contact persons."""


def get_contact_extraction_prompt() -> ChatPromptTemplate:
    """Return the versioned ChatPromptTemplate for decision-maker contact extraction."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", CONTACT_EXTRACTION_SYSTEM_PROMPT),
            ("human", CONTACT_EXTRACTION_HUMAN_PROMPT),
        ]
    )
