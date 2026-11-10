"""Company data model and structured LLM extraction schemas."""

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

from src.models.enums import CrawlStatus


class Company(BaseModel):
    """Core entity representing a Berlin property management company (Hausverwaltung)."""

    company_id: str = Field(..., description="Unique deterministic ID based on normalized domain or name")
    company_name: str = Field(..., min_length=2, description="Official or public company name")
    normalized_name: str = Field(default="", description="Lowercase normalized name stripped of legal suffixes")
    website: Optional[str] = Field(default=None, description="Official company website URL")
    domain: Optional[str] = Field(default=None, description="Normalized root domain (e.g., 'muster-hv.de')")
    address: Optional[str] = Field(default=None, description="Street address and house number")
    postal_code: Optional[str] = Field(default=None, description="5-digit German postal code (PLZ)")
    city: Optional[str] = Field(default=None, description="City name (e.g., Berlin)")
    phone: Optional[str] = Field(default=None, description="Official business phone number")
    general_email: Optional[str] = Field(
        default=None,
        description="General company contact email (e.g., info@), kept separate from individual decision-maker emails",
    )
    description: Optional[str] = Field(default=None, description="Concise business description")

    # Portfolio metrics (strictly nullable - never invented)
    managed_buildings: Optional[int] = Field(
        default=None, ge=0, description="Number of managed buildings/objects (Objekte / Liegenschaften)"
    )
    managed_residential_units: Optional[int] = Field(
        default=None, ge=0, description="Number of managed residential units (Wohneinheiten)"
    )
    managed_commercial_units: Optional[int] = Field(
        default=None, ge=0, description="Number of managed commercial units (Gewerbeeinheiten)"
    )
    managed_total_units: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total managed units when website states overall 'Verwaltete Einheiten' without splitting res/comm",
    )

    # Qualitative business profile
    property_types: List[str] = Field(
        default_factory=list,
        description="Types of properties managed (e.g., WEG-Verwaltung, Mietverwaltung, Gewerbeverwaltung, SEV)",
    )
    services: List[str] = Field(
        default_factory=list,
        description="Specific property and building management services offered",
    )
    metering_relevance: Optional[str] = Field(
        default=None,
        description="Assessment of heating, water, submetering, billing (HKVO), smoke detector, or ERP relevance",
    )
    metering_signals: List[str] = Field(
        default_factory=list,
        description="Explicit keywords/signals found (e.g., Betriebskostenabrechnung, Heizkosten, Casavi, Domus)",
    )
    company_size: Optional[str] = Field(
        default=None, description="Text description of company size (e.g., '18 Mitarbeiter')"
    )
    employee_count: Optional[int] = Field(
        default=None, ge=1, description="Explicit number of employees if publicly stated"
    )
    berlin_presence: Optional[str] = Field(
        default=None, description="Details of headquarters or operational presence in Berlin"
    )
    geographic_coverage: List[str] = Field(
        default_factory=list, description="Regions or districts covered (e.g., Berlin, Potsdam, Brandenburg)"
    )
    growth_signals: List[str] = Field(
        default_factory=list,
        description="Expansion, digitalization, association memberships (VDIV/BVI), or active hiring signals",
    )
    cooperation_notes: Optional[str] = Field(
        default=None, description="Relevant business context for potential Heidi Systems cooperation"
    )

    # Traceability and crawl metadata
    source_urls: List[str] = Field(default_factory=list, description="All public URLs used to build this record")
    crawl_status: CrawlStatus = Field(default=CrawlStatus.PENDING, description="Status of website scraping")
    crawl_limitations: Optional[str] = Field(
        default=None, description="Documented limitations (e.g., JS-heavy site, robots restriction, missing counts)"
    )
    is_sample_record: bool = Field(
        default=False, description="True ONLY for synthetic unit test fixtures; False for real leads"
    )
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def effective_total_units(self) -> Optional[int]:
        """Return total managed units by summing residential + commercial or falling back to managed_total_units."""
        if self.managed_residential_units is not None or self.managed_commercial_units is not None:
            res = self.managed_residential_units or 0
            comm = self.managed_commercial_units or 0
            summed = res + comm
            if self.managed_total_units is not None and self.managed_total_units > summed:
                return self.managed_total_units
            return summed
        return self.managed_total_units
