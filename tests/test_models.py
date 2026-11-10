"""Unit tests for data models, configuration, and repository persistence."""

from pathlib import Path
import pytest
from pydantic import ValidationError

from src.config import Settings
from src.models import (
    Company,
    Contact,
    CrawlStatus,
    EmailStatus,
    Evidence,
    KPIScoreBreakdown,
    LeadPriority,
    LeadQualification,
    SourceType,
    VerificationStatus,
    generate_contact_id,
    generate_evidence_id,
)
from src.storage import LeadRepository


def test_company_model_and_effective_units():
    """Verify Company schema validation, null handling, and effective unit calculation."""
    company = Company(
        company_id="comp_test_01",
        company_name="[SYNTHETIC TEST] Spree Hausverwaltung GmbH",
        normalized_name="spree hausverwaltung",
        website="https://example-spree-hv.de",
        domain="example-spree-hv.de",
        postal_code="10115",
        city="Berlin",
        managed_residential_units=450,
        managed_commercial_units=50,
        property_types=["WEG-Verwaltung", "Mietverwaltung"],
        is_sample_record=True,
    )
    assert company.effective_total_units() == 500
    assert company.managed_buildings is None
    assert company.crawl_status == CrawlStatus.PENDING


def test_company_effective_units_fallback_to_total():
    """When only overall managed_total_units is stated, effective_total_units returns it."""
    company = Company(
        company_id="comp_test_02",
        company_name="[SYNTHETIC TEST] Havel Immobilienverwaltung",
        managed_total_units=1200,
        is_sample_record=True,
    )
    assert company.effective_total_units() == 1200


def test_evidence_model_requires_supporting_text():
    """Ensure Evidence rejects empty supporting text to prevent unsupported claims."""
    ev_id = generate_evidence_id("comp_1", "managed_buildings", "https://example.de", "35")
    evidence = Evidence(
        evidence_id=ev_id,
        company_id="comp_1",
        field_name="managed_buildings",
        extracted_value="35",
        source_url="https://example.de/ueber-uns",
        source_type=SourceType.TEAM_PAGE,
        supporting_text="Wir verwalten aktuell 35 Liegenschaften in Berlin.",
        verification_status=VerificationStatus.VERIFIED_TEXT_MATCH,
    )
    assert evidence.evidence_id.startswith("ev_")

    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="ev_bad",
            company_id="comp_1",
            field_name="managed_buildings",
            extracted_value="35",
            source_url="https://example.de",
            supporting_text="",  # Must fail min_length=3
        )


def test_contact_model_and_email_status():
    """Verify Contact model and strict EmailStatus enumeration."""
    cid = generate_contact_id("comp_1", "Max Mustermann", "Geschäftsführer")
    contact = Contact(
        contact_id=cid,
        company_id="comp_1",
        company_name="[SYNTHETIC TEST] Spree Hausverwaltung GmbH",
        full_name="Max Mustermann",
        position="Geschäftsführer",
        role_priority_tier=1,
        professional_email=None,
        email_status=EmailStatus.NOT_FOUND,
        source_url="https://example-spree-hv.de/impressum",
        supporting_text="Vertreten durch den Geschäftsführer: Max Mustermann",
    )
    assert contact.contact_id.startswith("ct_")
    assert contact.email_status == EmailStatus.NOT_FOUND


def test_lead_qualification_model():
    """Verify LeadQualification and KPIScoreBreakdown validation."""
    breakdown = KPIScoreBreakdown(
        kpi_name="berlin_presence",
        max_score=15.0,
        awarded_score=15.0,
        effective_points=15.0,
        is_known=True,
        rationale="Verified HQ in 10115 Berlin.",
        supporting_evidence_ids=["ev_123"],
    )
    qual = LeadQualification(
        company_id="comp_1",
        company_name="[SYNTHETIC TEST] Spree Hausverwaltung GmbH",
        individual_kpi_scores={"berlin_presence": breakdown},
        raw_score=75.0,
        normalized_known_score=85.0,
        total_score=78.0,
        lead_priority=LeadPriority.HIGH,
        qualification_reason="High priority Berlin WEG & rental manager.",
        data_completeness=85.0,
        confidence="High",
    )
    assert qual.lead_priority == LeadPriority.HIGH
    assert qual.total_score == 78.0


def test_repository_persistence_and_sample_filtering(tmp_path: Path):
    """Verify JSON persistence and that sample records are filtered out by default."""
    settings = Settings(
        DATA_DIR=tmp_path / "data",
        CACHE_DIR=tmp_path / "data/cache",
        OUTPUT_DIR=tmp_path / "data/output",
        KPI_CONFIG_PATH=Path("config/kpi_weights.yaml"),
    )
    repo = LeadRepository(settings)

    sample_comp = Company(
        company_id="sample_1",
        company_name="[SYNTHETIC] Sample HV",
        is_sample_record=True,
    )
    real_comp = Company(
        company_id="real_1",
        company_name="Real Berlin HV GmbH",
        is_sample_record=False,
    )

    repo.upsert_company(sample_comp)
    repo.upsert_company(real_comp)
    repo.save_all()

    # Reload into a new repository instance
    repo2 = LeadRepository(settings)
    assert len(repo2.list_companies(include_samples=False)) == 1
    assert repo2.list_companies(include_samples=False)[0].company_id == "real_1"
    assert len(repo2.list_companies(include_samples=True)) == 2
