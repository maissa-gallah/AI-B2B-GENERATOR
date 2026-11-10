"""Unit tests for the 5-sheet Excel export service."""

from pathlib import Path
from openpyxl import load_workbook

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
from src.services.exporter import ExportService
from src.services.qualification import LeadQualificationService


def test_five_sheet_excel_generation_and_structure(tmp_path: Path):
    """Verify that ExportService produces a valid 5-sheet Excel workbook with all required sheets and columns."""
    settings = Settings(
        DATA_DIR=tmp_path / "data",
        CACHE_DIR=tmp_path / "data/cache",
        OUTPUT_DIR=tmp_path / "data/output",
        KPI_CONFIG_PATH=Path("config/kpi_weights.yaml"),
    )
    qual_service = LeadQualificationService(settings)
    exporter = ExportService(settings)

    comp = Company(
        company_id="comp_exp_1",
        company_name="[SYNTHETIC TEST] Muster Hausverwaltung Berlin GmbH",
        website="https://example-muster-hv.de",
        address="Friedrichstraße 100",
        postal_code="10117",
        city="Berlin",
        phone="030 123456",
        managed_buildings=25,
        managed_residential_units=600,
        property_types=["WEG-Verwaltung", "Mietverwaltung"],
        services=["Betriebskostenabrechnung", "Heizkostenabrechnung"],
        metering_signals=["Heizkostenabrechnung", "Casavi"],
        berlin_presence="Headquarters in 10117 Berlin",
        source_urls=["https://example-muster-hv.de", "https://example-muster-hv.de/impressum"],
        is_sample_record=True,
    )
    ev = Evidence(
        evidence_id="ev_exp_1",
        company_id="comp_exp_1",
        field_name="managed_residential_units",
        extracted_value="600",
        source_url="https://example-muster-hv.de",
        source_type=SourceType.COMPANY_HOMEPAGE,
        supporting_text="Über 600 Wohneinheiten in 25 Häusern.",
        verification_status=VerificationStatus.VERIFIED_TEXT_MATCH,
    )
    contact = Contact(
        contact_id="ct_exp_1",
        company_id="comp_exp_1",
        company_name=comp.company_name,
        full_name="Erika Muster",
        position="Geschäftsführerin",
        role_priority_tier=1,
        professional_email="e.muster@example-muster-hv.de",
        is_generic_email=False,
        email_status=EmailStatus.PUBLICLY_PUBLISHED,
        source_url="https://example-muster-hv.de/impressum",
        supporting_text="Geschäftsführerin: Erika Muster",
    )

    qual = qual_service.qualify_company(comp, [ev], [contact])
    assert qual.lead_priority == LeadPriority.HIGH

    xlsx_path = exporter.export_to_excel(
        companies=[comp],
        qualifications=[qual],
        contacts=[contact],
        evidences=[ev],
        output_filename="test_deliverable.xlsx",
    )

    assert xlsx_path.exists()
    wb = load_workbook(xlsx_path)
    expected_sheets = [
        "Companies",
        "Lead Qualification",
        "Contacts",
        "Sources and Validation",
        "Methodology",
    ]
    assert wb.sheetnames == expected_sheets

    # Check data rows exist in each sheet
    assert wb["Companies"].max_row == 2
    assert wb["Lead Qualification"].max_row == 2
    assert wb["Contacts"].max_row == 2
    assert wb["Sources and Validation"].max_row == 2
    assert wb["Methodology"].max_row >= 8
