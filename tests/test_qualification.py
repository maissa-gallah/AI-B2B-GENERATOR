"""Unit tests for deterministic KPI scoring, lead priority classification, and missing data handling."""

from pathlib import Path

from src.config import Settings
from src.models import (
    Company,
    Contact,
    EmailStatus,
    Evidence,
    LeadPriority,
    SourceType,
    VerificationStatus,
)
from src.services.qualification import LeadQualificationService


def _get_service(tmp_path: Path) -> LeadQualificationService:
    settings = Settings(
        DATA_DIR=tmp_path / "data",
        CACHE_DIR=tmp_path / "data/cache",
        OUTPUT_DIR=tmp_path / "data/output",
        KPI_CONFIG_PATH=Path("config/kpi_weights.yaml"),
    )
    return LeadQualificationService(settings)


def test_high_priority_lead_with_complete_data(tmp_path: Path):
    """A Berlin WEG & Mietverwaltung with large unit count, billing/ERP, and direct GF contact scores High."""
    service = _get_service(tmp_path)
    company = Company(
        company_id="comp_high_1",
        company_name="[SYNTHETIC TEST] Berlin Top Hausverwaltung GmbH",
        website="https://example-top-hv.de",
        postal_code="10117",
        city="Berlin",
        managed_buildings=65,
        managed_residential_units=2400,
        managed_commercial_units=150,
        property_types=["WEG-Verwaltung", "Mietverwaltung"],
        services=["Betriebskostenabrechnung", "Heizkostenabrechnung", "Technische Verwaltung"],
        metering_signals=["Heizkostenabrechnung", "Casavi Kundenportal", "Domus ERP"],
        employee_count=25,
        growth_signals=["VDIV Mitglied", "Digitales Kundenportal (Casavi)"],
        is_sample_record=True,
    )
    contact = Contact(
        contact_id="ct_high_1",
        company_id="comp_high_1",
        company_name=company.company_name,
        full_name="Dr. Anna Beispiel",
        position="Geschäftsführerin",
        role_priority_tier=1,
        professional_email="a.beispiel@example-top-hv.de",
        is_generic_email=False,
        email_status=EmailStatus.PUBLICLY_PUBLISHED,
        source_url="https://example-top-hv.de/impressum",
    )
    ev = Evidence(
        evidence_id="ev_1",
        company_id="comp_high_1",
        field_name="managed_residential_units",
        extracted_value="2400",
        source_url="https://example-top-hv.de",
        source_type=SourceType.COMPANY_HOMEPAGE,
        supporting_text="Wir verwalten 2.400 Wohneinheiten und 150 Gewerbeeinheiten in 65 Objekten.",
        verification_status=VerificationStatus.VERIFIED_TEXT_MATCH,
    )

    qual = service.qualify_company(company, [ev], [contact])
    assert qual.total_score == 100.0
    assert qual.data_completeness == 100.0
    assert qual.lead_priority == LeadPriority.HIGH
    assert qual.confidence == "High"


def test_missing_portfolio_counts_handled_neutrally_not_penalized(tmp_path: Path):
    """When unit, building, and employee counts are unknown (null), a strong Berlin WEG/Mietverwaltung still qualifies High."""
    service = _get_service(tmp_path)
    company = Company(
        company_id="comp_missing_nums",
        company_name="[SYNTHETIC TEST] Charlottenburger WEG & Mietverwaltung GmbH",
        website="https://example-charlottenburg-hv.de",
        postal_code="10627",
        city="Berlin",
        # Quantitative counts are all None (very common on German Hausverwaltung sites)
        managed_buildings=None,
        managed_residential_units=None,
        managed_commercial_units=None,
        employee_count=None,
        property_types=["WEG-Verwaltung", "Mietverwaltung"],
        services=["Betriebskostenabrechnung", "Hausgeldabrechnung", "Technische Gebäudeverwaltung"],
        metering_signals=["Betriebskostenabrechnung", "Kundenportal"],
        growth_signals=["VDIV Mitglied", "Digitales Kundenportal"],
        is_sample_record=True,
    )
    contact = Contact(
        contact_id="ct_charl_1",
        company_id="comp_missing_nums",
        company_name=company.company_name,
        full_name="Thomas Tester",
        position="Geschäftsführer",
        role_priority_tier=1,
        professional_email="t.tester@example-charlottenburg-hv.de",
        is_generic_email=False,
        email_status=EmailStatus.TECHNICALLY_DELIVERABILITY_CHECKED,
        source_url="https://example-charlottenburg-hv.de/impressum",
    )

    qual = service.qualify_company(company, [], [contact])

    # Verify unknown quantitative KPIs are marked is_known=False
    assert qual.individual_kpi_scores["managed_units"].is_known is False
    assert qual.individual_kpi_scores["managed_buildings"].is_known is False
    assert qual.individual_kpi_scores["company_size"].is_known is False

    # Known weight = 15 (Berlin) + 20 (Property Types) + 20 (Metering) + 10 (Decision-Makers) + 5 (Growth) = 70%
    assert qual.data_completeness == 70.0
    assert qual.raw_score == 70.0
    assert qual.normalized_known_score == 100.0
    # Blended score = 0.70 * 70 + 0.30 * 100 = 79.0 -> High Priority!
    assert qual.total_score == 79.0
    assert qual.lead_priority == LeadPriority.HIGH


def test_insufficient_information_classification(tmp_path: Path):
    """A stub record with almost no known fields is classified as Insufficient Information."""
    service = _get_service(tmp_path)
    empty_comp = Company(
        company_id="comp_empty",
        company_name="[SYNTHETIC TEST] Empty Stub GmbH",
        is_sample_record=True,
    )
    qual = service.qualify_company(empty_comp, [], [])
    assert qual.lead_priority == LeadPriority.INSUFFICIENT_INFORMATION
    assert qual.confidence == "Low"
