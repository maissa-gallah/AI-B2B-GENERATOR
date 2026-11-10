"""Unit tests for company normalization, deduplication, and anti-hallucination evidence validation."""

from src.models import (
    Company,
    Evidence,
    SourceType,
    VerificationStatus,
    generate_evidence_id,
)
from src.services.validation import (
    ValidationService,
    extract_root_domain,
    normalize_company_name,
    normalize_phone,
)


def test_domain_and_name_normalization():
    """Verify root domain extraction and German legal suffix removal."""
    assert extract_root_domain("https://www.Berliner-Hausverwaltung.de/leistungen/") == "berliner-hausverwaltung.de"
    assert extract_root_domain("http://sub.hv-berlin.com:8080/test") == "sub.hv-berlin.com"

    assert normalize_company_name("Spree & Havel Hausverwaltung GmbH & Co. KG") == "spree havel hausverwaltung"
    assert normalize_company_name("Müller Immobilienverwaltung UG (haftungsbeschränkt)") == "mueller immobilienverwaltung"
    assert normalize_phone("+49 (0)30 123 456 - 0") == "0301234560"


def test_deduplicate_companies_by_domain_and_name():
    """Ensure duplicate companies from multiple search queries are merged without losing data."""
    validator = ValidationService(excluded_domains=["immobilienscout24.de", "yelp.de"])

    c1 = Company(
        company_id="temp_1",
        company_name="[SYNTHETIC] Kronen Hausverwaltung GmbH | Startseite",
        website="https://www.kronen-hv-berlin.de/home",
        postal_code="10117",
        city="Berlin",
        source_urls=["https://www.kronen-hv-berlin.de/home"],
        is_sample_record=True,
    )
    c2 = Company(
        company_id="temp_2",
        company_name="Kronen Hausverwaltung GmbH",
        website="https://kronen-hv-berlin.de/weg-verwaltung",
        phone="030 9876543",
        property_types=["WEG-Verwaltung"],
        source_urls=["https://kronen-hv-berlin.de/weg-verwaltung"],
        is_sample_record=True,
    )
    c3 = Company(
        company_id="temp_3",
        company_name="Kronen Hausverwaltung UG",  # Different legal suffix, no website in snippet, same phone
        phone="+49 30 9876543",
        services=["Betriebskostenabrechnung"],
        source_urls=["https://directory.example.de/kronen"],
        is_sample_record=True,
    )

    deduped = validator.deduplicate_companies([c1, c2, c3])
    assert len(deduped) == 1
    merged = deduped[0]
    assert merged.company_name == "Kronen Hausverwaltung GmbH"
    assert merged.domain == "kronen-hv-berlin.de"
    assert merged.postal_code == "10117"
    assert merged.phone == "030 9876543"
    assert "WEG-Verwaltung" in merged.property_types
    assert "Betriebskostenabrechnung" in merged.services
    assert len(merged.source_urls) == 3


def test_excluded_domains_filtering():
    """Ensure aggregator and social domains are flagged as excluded."""
    validator = ValidationService(excluded_domains=["immobilienscout24.de", "linkedin.com", "heidisystems.com"])
    assert validator.is_excluded_domain("https://www.immobilienscout24.de/anbieter/berlin") is True
    assert validator.is_excluded_domain("https://de.linkedin.com/company/test") is True
    assert validator.is_excluded_domain("https://heidisystems.com") is True
    assert validator.is_excluded_domain("https://www.allod.de") is False


def test_anti_hallucination_strips_unsupported_numbers():
    """Ensure quantitative fields without matching evidence quotes are stripped to None."""
    validator = ValidationService()
    comp = Company(
        company_id="comp_hallucination_test",
        company_name="[SYNTHETIC] Test HV",
        managed_residential_units=1500,  # Backed by evidence
        managed_buildings=99,  # Hallucinated (no evidence record!)
        employee_count=45,  # Evidence record exists, but quote doesn't contain '45'
        is_sample_record=True,
    )

    ev_units = Evidence(
        evidence_id=generate_evidence_id(comp.company_id, "managed_residential_units", "https://testhv.de", "1500"),
        company_id=comp.company_id,
        field_name="managed_residential_units",
        extracted_value="1500",
        source_url="https://testhv.de",
        source_type=SourceType.COMPANY_HOMEPAGE,
        supporting_text="Wir betreuen über 1.500 Wohneinheiten in ganz Berlin.",
        verification_status=VerificationStatus.VERIFIED_TEXT_MATCH,
    )
    ev_emp_bad = Evidence(
        evidence_id=generate_evidence_id(comp.company_id, "employee_count", "https://testhv.de", "45"),
        company_id=comp.company_id,
        field_name="employee_count",
        extracted_value="45",
        source_url="https://testhv.de",
        source_type=SourceType.COMPANY_HOMEPAGE,
        supporting_text="Unser erfahrenes Team steht Ihnen jederzeit zur Verfügung.",  # Number 45 is NOT in quote
        verification_status=VerificationStatus.UNVERIFIED,
    )

    cleaned_comp, valid_evs = validator.enforce_company_evidence_consistency(comp, [ev_units, ev_emp_bad])
    assert cleaned_comp.managed_residential_units == 1500
    assert cleaned_comp.managed_buildings is None
    assert cleaned_comp.employee_count is None
    assert len(valid_evs) == 2
