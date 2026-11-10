"""Prompt v1.0 for extracting structured company & portfolio information with verbatim evidence."""

from typing import List, Optional
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

PROMPT_VERSION = "1.0.0"


class EvidenceItemSchema(BaseModel):
    """Schema for a single piece of supporting evidence returned by the LLM."""

    field_name: str = Field(
        ...,
        description=(
            "Exact field name being supported (e.g., 'managed_buildings', "
            "'managed_residential_units', 'managed_commercial_units', 'managed_total_units', "
            "'property_types', 'services', 'employee_count', 'berlin_presence', 'growth_signals')"
        ),
    )
    extracted_value: str = Field(..., description="String value of the extracted fact")
    source_url: str = Field(..., description="Exact PAGE SOURCE_URL where the quote was found")
    supporting_text: str = Field(
        ...,
        description="Verbatim quote copied directly from the website text that proves this value",
    )


class CompanyExtractionLLMOutput(BaseModel):
    """Structured LLM output for Task 2 (Company Information Extraction) and Metering Relevance."""

    official_company_name: Optional[str] = Field(
        default=None, description="Official company name (e.g., from Impressum or header)"
    )
    address: Optional[str] = Field(
        default=None, description="Street address and house number (e.g., 'Kurfürstendamm 123')"
    )
    postal_code: Optional[str] = Field(
        default=None, description="5-digit German postal code (e.g., '10719')"
    )
    city: Optional[str] = Field(default=None, description="City name (e.g., 'Berlin')")
    phone: Optional[str] = Field(default=None, description="Official business phone number")
    general_email: Optional[str] = Field(
        default=None, description="General company email address (e.g., info@...)"
    )
    description: Optional[str] = Field(
        default=None, description="1-2 sentence factual summary of the company's property management business"
    )

    # Quantitative counts - MUST BE NULL unless explicitly stated in text
    managed_buildings: Optional[int] = Field(
        default=None,
        description="Explicit number of managed buildings/objects (Objekte, Liegenschaften, Häuser). Null if not stated.",
    )
    managed_residential_units: Optional[int] = Field(
        default=None,
        description="Explicit number of managed residential units (Wohneinheiten). Null if not stated.",
    )
    managed_commercial_units: Optional[int] = Field(
        default=None,
        description="Explicit number of managed commercial units (Gewerbeeinheiten). Null if not stated.",
    )
    managed_total_units: Optional[int] = Field(
        default=None,
        description="Explicit total number of managed units (Verwaltete Einheiten / Wohn- und Gewerbeeinheiten) when not split. Null if not stated.",
    )
    employee_count: Optional[int] = Field(
        default=None,
        description="Explicit number of employees (Mitarbeiter). Null if not stated.",
    )
    company_size: Optional[str] = Field(
        default=None,
        description="Text description of team/company size if stated, else null.",
    )

    # Categorical & qualitative fields
    property_types: List[str] = Field(
        default_factory=list,
        description=(
            "Standardized property management types offered. Use canonical labels where applicable: "
            "'WEG-Verwaltung', 'Mietverwaltung', 'Gewerbeverwaltung', 'Sondereigentumsverwaltung (SEV)', 'Zinshausverwaltung'"
        ),
    )
    services: List[str] = Field(
        default_factory=list,
        description="Specific property and building management services mentioned on the website",
    )
    metering_relevance: Optional[str] = Field(
        default=None,
        description=(
            "Concise analysis of evidence related to heating/water billing (Heizkostenabrechnung, "
            "Betriebskostenabrechnung, Hausgeldabrechnung), technical management, smoke detectors, "
            "or digital ERP/customer portals (Casavi, Domus, Wodis, Haufe, Immoware24, Kundenportal)."
        ),
    )
    metering_signals: List[str] = Field(
        default_factory=list,
        description="Specific keywords/tools found (e.g., 'Betriebskostenabrechnung', 'Heizkostenabrechnung', 'Technische Verwaltung', 'Casavi', 'Domus', 'Kundenportal')",
    )
    berlin_presence: Optional[str] = Field(
        default=None,
        description="Explanation of headquarters location and operational presence in Berlin",
    )
    geographic_coverage: List[str] = Field(
        default_factory=list,
        description="Cities or regions covered (e.g., 'Berlin', 'Potsdam', 'Brandenburg')",
    )
    growth_signals: List[str] = Field(
        default_factory=list,
        description="Evidence of growth, hiring/careers, digital transformation, or association memberships (e.g., VDIV, BVI, IVD)",
    )
    cooperation_notes: Optional[str] = Field(
        default=None,
        description="Why this company is (or is not) a relevant prospect for Heidi Systems (digital submetering & heating billing)",
    )
    evidence_items: List[EvidenceItemSchema] = Field(
        default_factory=list,
        description="Mandatory list of verbatim quotes and source URLs backing every extracted field.",
    )


COMPANY_EXTRACTION_SYSTEM_PROMPT = """You are a Senior B2B Real Estate Analyst extracting factual data about German property management companies (Hausverwaltungen) in Berlin for Heidi Systems (a digital submetering and heating/water cost billing provider).

STRICT ANTI-HALLUCINATION RULES:
1. NEVER invent, estimate, or guess numbers for `managed_buildings`, `managed_residential_units`, `managed_commercial_units`, `managed_total_units`, or `employee_count`.
2. If a number is not explicitly written in the provided website text, you MUST return `null` (None).
3. Every non-null quantitative metric and key qualitative claim MUST have a corresponding entry in `evidence_items` with the exact `source_url` from the `=== PAGE SOURCE_URL: ... ===` header and a verbatim `supporting_text` quote copied directly from the text.
4. Distinguish between:
   - `managed_buildings` (Objekte, Liegenschaften, Häuser, Gebäude, WEGs)
   - `managed_residential_units` (Wohneinheiten)
   - `managed_commercial_units` (Gewerbeeinheiten)
   - `managed_total_units` (Verwaltete Einheiten / Einheiten insgesamt when not separated)
5. Look carefully for metering and billing relevance:
   - Heating/utility billing: Heizkostenabrechnung, Betriebskostenabrechnung, Nebenkostenabrechnung, Hausgeldabrechnung, Jahresabrechnung
   - Technical management: Technische Gebäudeverwaltung, Instandhaltung, Haustechnik, Rauchwarnmelder, Messdienste
   - Digitalization / ERP systems: Kundenportal, Eigentümerportal, Mieterportal, Casavi, Domus, Wodis, Haufe, Immoware24, Karthago, GFAD
   - Industry associations: VDIV, BVI, IVD, RICS

Respond strictly with valid JSON matching the requested schema."""

COMPANY_EXTRACTION_HUMAN_PROMPT = """Company Name Candidate: {company_name}
Company Website: {website}

Scraped Website Content (with PAGE SOURCE_URL headers):
{website_text}

Extract the structured company profile, metering relevance analysis, and verbatim evidence items."""


def get_company_extraction_prompt() -> ChatPromptTemplate:
    """Return the versioned ChatPromptTemplate for company and metering extraction."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", COMPANY_EXTRACTION_SYSTEM_PROMPT),
            ("human", COMPANY_EXTRACTION_HUMAN_PROMPT),
        ]
    )
