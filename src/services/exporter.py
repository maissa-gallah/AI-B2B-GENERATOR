"""Export Service for generating the professionally formatted 5-sheet Excel workbook."""

from pathlib import Path
from typing import Any, Dict, List
import logging

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.config import Settings
from src.models import Company, Contact, Evidence, LeadPriority, LeadQualification

logger = logging.getLogger(__name__)


class ExportService:
    """Generates a multi-sheet, styled, filterable Excel deliverable for sales prospecting."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def export_to_excel(
        self,
        companies: List[Company],
        qualifications: List[LeadQualification],
        contacts: List[Contact],
        evidences: List[Evidence],
        output_filename: str = "heidi_berlin_leads.xlsx",
    ) -> Path:
        """Create the 5-sheet Excel workbook and apply professional OpenPyXL styling."""
        self.settings.ensure_directories()
        output_path = self.settings.output_dir / output_filename

        qual_by_comp: Dict[str, LeadQualification] = {q.company_id: q for q in qualifications}
        # Sort companies by total lead score descending so top prospects appear first
        sorted_companies = sorted(
            companies,
            key=lambda c: qual_by_comp.get(c.company_id).total_score
            if c.company_id in qual_by_comp
            else -1.0,
            reverse=True,
        )

        df_companies = self._build_companies_df(sorted_companies, qual_by_comp)
        df_qualification = self._build_qualification_df(sorted_companies, qual_by_comp)
        df_contacts = self._build_contacts_df(contacts, qual_by_comp)
        df_sources = self._build_sources_df(sorted_companies, evidences)
        df_methodology = self._build_methodology_df()

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            df_companies.to_excel(writer, sheet_name="Companies", index=False)
            df_qualification.to_excel(writer, sheet_name="Lead Qualification", index=False)
            df_contacts.to_excel(writer, sheet_name="Contacts", index=False)
            df_sources.to_excel(writer, sheet_name="Sources and Validation", index=False)
            df_methodology.to_excel(writer, sheet_name="Methodology", index=False)

        self._style_workbook(output_path)
        logger.info("Exported 5-sheet Excel deliverable to %s", output_path)
        return output_path

    def _build_companies_df(
        self, companies: List[Company], qual_by_comp: Dict[str, LeadQualification]
    ) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        for c in companies:
            q = qual_by_comp.get(c.company_id)
            rows.append(
                {
                    "Company ID": c.company_id,
                    "Company Name": c.company_name,
                    "Lead Priority": q.lead_priority.value if q else "Unqualified",
                    "Lead Score (0-100)": q.total_score if q else None,
                    "Website": c.website,
                    "Address": c.address,
                    "Postal Code": c.postal_code,
                    "City": c.city,
                    "Phone": c.phone,
                    "General Email": c.general_email,
                    "Property Types Managed": ", ".join(c.property_types) if c.property_types else None,
                    "Managed Buildings": c.managed_buildings,
                    "Managed Residential Units": c.managed_residential_units,
                    "Managed Commercial Units": c.managed_commercial_units,
                    "Effective Total Units": c.effective_total_units(),
                    "Services Offered": ", ".join(c.services) if c.services else None,
                    "Metering & Billing Relevance": c.metering_relevance,
                    "Metering Signals": ", ".join(c.metering_signals) if c.metering_signals else None,
                    "Company Size": c.company_size or (f"{c.employee_count} Mitarbeiter" if c.employee_count else None),
                    "Employee Count": c.employee_count,
                    "Berlin Presence": c.berlin_presence,
                    "Geographic Coverage": ", ".join(c.geographic_coverage) if c.geographic_coverage else None,
                    "Growth & Modernization Signals": ", ".join(c.growth_signals) if c.growth_signals else None,
                    "Cooperation Notes": c.cooperation_notes,
                    "Business Description": c.description,
                    "Source URLs": " | ".join(c.source_urls),
                    "Crawl Status": c.crawl_status.value,
                }
            )
        return pd.DataFrame(rows)

    def _build_qualification_df(
        self, companies: List[Company], qual_by_comp: Dict[str, LeadQualification]
    ) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        for c in companies:
            q = qual_by_comp.get(c.company_id)
            if not q:
                continue

            def _kpi_val(key: str) -> str:
                b = q.individual_kpi_scores.get(key)
                if not b:
                    return "N/A"
                if not b.is_known:
                    return f"Unknown (Max {b.max_score:.0f})"
                return f"{b.effective_points:.1f} / {b.max_score:.0f}"

            rows.append(
                {
                    "Company ID": q.company_id,
                    "Company Name": c.company_name,
                    "Website": c.website,
                    "Lead Priority": q.lead_priority.value,
                    "Total Score (0-100)": q.total_score,
                    "Raw Verified Points": q.raw_score,
                    "Known-Normalized Score": q.normalized_known_score,
                    "Data Completeness (%)": q.data_completeness,
                    "Qualification Confidence": q.confidence,
                    "KPI 1: Berlin Presence (15)": _kpi_val("berlin_presence"),
                    "KPI 2: Property Types (20)": _kpi_val("property_types"),
                    "KPI 3: Metering Relevance (20)": _kpi_val("metering_relevance"),
                    "KPI 4: Managed Units (15)": _kpi_val("managed_units"),
                    "KPI 5: Managed Buildings (10)": _kpi_val("managed_buildings"),
                    "KPI 6: Decision-Makers (10)": _kpi_val("decision_makers"),
                    "KPI 7: Company Size (5)": _kpi_val("company_size"),
                    "KPI 8: Growth Signals (5)": _kpi_val("growth_signals"),
                    "Qualification Explanation": q.qualification_reason,
                    "Scoring Version": q.scoring_version,
                }
            )
        return pd.DataFrame(rows)

    def _build_contacts_df(
        self, contacts: List[Contact], qual_by_comp: Dict[str, LeadQualification]
    ) -> pd.DataFrame:
        # Sort contacts by company score descending, then role priority tier
        sorted_contacts = sorted(
            contacts,
            key=lambda ct: (
                -(qual_by_comp.get(ct.company_id).total_score if ct.company_id in qual_by_comp else 0.0),
                ct.role_priority_tier,
                ct.is_generic_email,
            ),
        )
        rows: List[Dict[str, Any]] = []
        for ct in sorted_contacts:
            q = qual_by_comp.get(ct.company_id)
            rows.append(
                {
                    "Contact ID": ct.contact_id,
                    "Company ID": ct.company_id,
                    "Company Name": ct.company_name,
                    "Company Priority": q.lead_priority.value if q else "N/A",
                    "Full Name": ct.full_name,
                    "Position / Role": ct.position,
                    "Role Priority Tier": f"Tier {ct.role_priority_tier}",
                    "Professional Email": ct.professional_email,
                    "Email Type": "Generic Mailbox (info@/kontakt@)" if ct.is_generic_email else ("Direct / Personal" if ct.professional_email else "Not Listed"),
                    "Contact Verification Status": ct.email_status.value,
                    "LinkedIn Profile": ct.linkedin_url,
                    "Source URL": ct.source_url,
                    "Supporting Quote / Evidence": ct.supporting_text,
                }
            )
        return pd.DataFrame(rows)

    def _build_sources_df(
        self, companies: List[Company], evidences: List[Evidence]
    ) -> pd.DataFrame:
        comp_name_map = {c.company_id: c.company_name for c in companies}
        comp_limit_map = {c.company_id: c.crawl_limitations for c in companies}
        rows: List[Dict[str, Any]] = []
        for ev in evidences:
            rows.append(
                {
                    "Evidence ID": ev.evidence_id,
                    "Company ID": ev.company_id,
                    "Company Name": comp_name_map.get(ev.company_id, ""),
                    "Field Name": ev.field_name,
                    "Extracted Value": ev.extracted_value,
                    "Supporting Evidence Quote": ev.supporting_text,
                    "Source URL": ev.source_url,
                    "Source Type": ev.source_type.value,
                    "Verification Status": ev.verification_status.value,
                    "Extraction Timestamp (UTC)": ev.extraction_timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "Crawl / Data Limitations": comp_limit_map.get(ev.company_id) or "None",
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _build_methodology_df() -> pd.DataFrame:
        sections = [
            (
                "1. Business Context: Heidi Systems GmbH",
                "Heidi Systems GmbH (Monbijouplatz, Berlin, HRB 259535 B) is a digital submetering service provider (Messdienstleister) "
                "and PropTech platform. It provides radio-based heat cost allocators, hot/cold water meters, smart smoke detectors, "
                "seamless takeover of existing OMS meters mid-contract (Bestandszähler-Übernahme), automated HKVO/MessEG compliant heating "
                "and utility billing (Heizkostenabrechnung), monthly consumption info (uVI), and automated ERP interfaces for Hausverwaltungen.",
            ),
            (
                "2. Discovery Strategy",
                "Multi-query German search discovery targeting Berlin property management companies across segments: "
                "'Hausverwaltung Berlin WEG Mietverwaltung', 'Immobilienverwaltung Berlin GmbH', 'WEG-Verwaltung Berlin Wohneinheiten', "
                "'Mietverwaltung Berlin Zinshausverwaltung', 'Gewerbeimmobilienverwaltung Berlin', and 'Hausverwaltung Berlin VDIV Mitglied'. "
                "Supports Tavily API, Exa API, Brave Search API, and keyless DuckDuckGo/directory discovery with strict portal filtering.",
            ),
            (
                "3. Data Extraction Process",
                "Polite multi-page HTML crawler (requests + BeautifulSoup + lxml) fetching each company's homepage and up to 5 high-value "
                "subpages (/impressum, /ueber-uns, /team, /leistungen, /referenzen, /kontakt) while respecting robots.txt. "
                "LangChain + DeepSeek (deepseek-chat) extracts structured Pydantic objects with mandatory verbatim supporting quotes.",
            ),
            (
                "4. KPI Definitions & Maximum Weights (Total = 100 pts)",
                "• KPI 1: Berlin Presence & Operational Coverage (15 pts) - Verified HQ in Berlin (10xxx-14xxx) or active Berlin portfolio.\n"
                "• KPI 2: Relevance of Property Types (20 pts) - Both WEG & Mietverwaltung (20), Either WEG or Miet (16), Gewerbe/SEV (12).\n"
                "• KPI 3: Metering, Billing & ERP Relevance (20 pts) - Heating/utility billing + digital portal/ERP (20), Billing/Tech mgmt (15), Standard PM (10).\n"
                "• KPI 4: Managed Residential & Commercial Units (15 pts) - >=2000 (15), 500-1999 (12), 100-499 (9), 10-99 (5), 1-9 (2).\n"
                "• KPI 5: Managed Buildings / Properties (10 pts) - >=50 (10), 20-49 (8), 5-19 (5), 1-4 (2).\n"
                "• KPI 6: Availability of Decision-Makers (10 pts) - Named GF/Leader + direct email/LinkedIn (10), Named GF + company contact (7), Generic only (3).\n"
                "• KPI 7: Company Size (5 pts) - >=20 employees (5), 5-19 employees (3), 1-4 employees (1).\n"
                "• KPI 8: Growth & Modernization Signals (5 pts) - 2+ signals e.g. VDIV, digital portal, hiring (5), 1 signal (3).",
            ),
            (
                "5. Deterministic Scoring Formula & Missing Data Handling",
                "Missing information is NEVER automatically treated as a negative result. Many established German Hausverwaltungen do not "
                "publish exact unit or headcount numbers. When a metric is unknown (null), it is flagged as is_known=False. "
                "Python computes: Total Score = round(0.70 * Raw_Verified_Score + 0.30 * (Raw_Verified_Score / Known_Max_Weight * 100), 1). "
                "Priority Tiers: High (Score >= 70, Completeness >= 50%, Berlin WEG/Miet), Medium (Score >= 45), Low (< 45), "
                "Insufficient Information (Completeness < 35%).",
            ),
            (
                "6. Validation & Anti-Hallucination Rules",
                "1) Deterministic deduplication merges records by root domain, normalized company name (stripping GmbH/UG/KG), or phone/PLZ.\n"
                "2) Quantitative fields (buildings, units, employees) are automatically stripped to null if they lack a verbatim quote containing the number.\n"
                "3) Contact emails are never guessed; only emails explicitly published on the source HTML are retained and checked via DNS MX records.",
            ),
            (
                "7. Technology Stack",
                "Python 3.12, uv package manager, Pydantic v2, LangChain (langchain-core, langchain-openai), DeepSeek API (deepseek-chat), "
                "Requests, BeautifulSoup4, lxml, dnspython, FastAPI, Pandas, OpenPyXL, MongoDB / JSON persistence, Docker, Pytest.",
            ),
            (
                "8. Known Limitations",
                "1) JavaScript-heavy single-page applications (SPAs) may return minimal static HTML without a headless browser; these are logged in Crawl Status.\n"
                "2) Under German GDPR practices, many Hausverwaltungen publish only general mailboxes (info@) in their Impressum rather than personal emails.\n"
                "3) Portfolio counts (units/buildings) are self-reported marketing figures on company websites and reflect the date of website publication.",
            ),
        ]
        return pd.DataFrame(sections, columns=["Methodology Section", "Detailed Specification & Explanation"])

    def _style_workbook(self, file_path: Path) -> None:
        """Apply professional header colors, borders, auto-filters, freeze panes, and priority badges."""
        wb = load_workbook(file_path)

        header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        body_font = Font(name="Calibri", size=10, color="111111")
        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9"),
        )

        priority_fills = {
            LeadPriority.HIGH.value: PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid"),
            LeadPriority.MEDIUM.value: PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid"),
            LeadPriority.LOW.value: PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid"),
            LeadPriority.INSUFFICIENT_INFORMATION.value: PatternFill(
                start_color="E2E3E5", end_color="E2E3E5", fill_type="solid"
            ),
        }

        for ws in wb.worksheets:
            ws.views.sheetView[0].showGridLines = True
            ws.freeze_panes = "A2"
            if ws.max_row >= 1 and ws.max_column >= 1:
                ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"

            # Style header row
            for col_idx in range(1, ws.max_column + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                cell.border = thin_border
            ws.row_dimensions[1].height = 28

            # Style data rows and compute optimal column widths
            for col_idx in range(1, ws.max_column + 1):
                col_letter = get_column_letter(col_idx)
                header_text = str(ws.cell(row=1, column=col_idx).value or "")
                max_len = len(header_text)

                for row_idx in range(2, ws.max_row + 1):
                    cell = ws.cell(row=row_idx, column=col_idx)
                    val_str = str(cell.value or "")
                    max_len = max(max_len, min(len(val_str), 65))

                    cell.font = body_font
                    cell.border = thin_border
                    cell.alignment = Alignment(
                        vertical="top",
                        wrap_text=(len(val_str) > 45 or ws.title == "Methodology"),
                    )

                    # Highlight Lead Priority cells
                    if header_text in ("Lead Priority", "Company Priority") and val_str in priority_fills:
                        cell.fill = priority_fills[val_str]
                        cell.font = Font(name="Calibri", size=10, bold=True, color="111111")

                if ws.title == "Methodology":
                    ws.column_dimensions[col_letter].width = 38 if col_idx == 1 else 105
                else:
                    ws.column_dimensions[col_letter].width = max(14, min(max_len + 4, 52))

            if ws.title == "Methodology":
                for row_idx in range(2, ws.max_row + 1):
                    ws.row_dimensions[row_idx].height = 68

        wb.save(file_path)
