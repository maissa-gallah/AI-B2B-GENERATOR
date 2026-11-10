"""Lead Qualification Service implementing deterministic Python KPI scoring for Heidi Systems."""

from typing import Any, Dict, List

from src.config import Settings
from src.models import (
    Company,
    Contact,
    EmailStatus,
    Evidence,
    KPIScoreBreakdown,
    LeadPriority,
    LeadQualification,
)


class LeadQualificationService:
    """Calculates deterministic KPI scores, completeness %, confidence, and priority tiers."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.kpi_config: Dict[str, Any] = self.settings.load_kpi_config()
        self.scoring_version: str = str(self.kpi_config.get("scoring_version", "1.0.0"))

    def qualify_company(
        self,
        company: Company,
        evidences: List[Evidence],
        contacts: List[Contact],
    ) -> LeadQualification:
        """Deterministically evaluate a Company across all 8 KPIs and compute final qualification."""
        ev_by_field: Dict[str, List[str]] = {}
        for ev in evidences:
            if ev.company_id == company.company_id:
                ev_by_field.setdefault(ev.field_name, []).append(ev.evidence_id)

        breakdowns: Dict[str, KPIScoreBreakdown] = {
            "berlin_presence": self._score_berlin_presence(company, ev_by_field),
            "property_types": self._score_property_types(company, ev_by_field),
            "metering_relevance": self._score_metering_relevance(company, ev_by_field),
            "managed_units": self._score_managed_units(company, ev_by_field),
            "managed_buildings": self._score_managed_buildings(company, ev_by_field),
            "decision_makers": self._score_decision_makers(company, contacts),
            "company_size": self._score_company_size(company, ev_by_field),
            "growth_signals": self._score_growth_signals(company, ev_by_field),
        }

        total_max_weight = sum(b.max_score for b in breakdowns.values())
        known_max_weight = sum(b.max_score for b in breakdowns.values() if b.is_known)
        raw_score = sum(b.effective_points for b in breakdowns.values())

        # Data completeness is the percentage of total KPI weight for which verified information exists
        data_completeness = (
            round((known_max_weight / total_max_weight) * 100.0, 1)
            if total_max_weight > 0
            else 0.0
        )

        # Normalized score across known KPIs ensures missing quantitative metrics (e.g., unit counts)
        # do not automatically penalize a strong Berlin WEG/Mietverwaltung as if it had 0 units.
        normalized_known_score = (
            round((raw_score / known_max_weight) * 100.0, 1)
            if known_max_weight > 0
            else 0.0
        )

        formula_cfg = self.kpi_config.get("scoring_formula", {})
        raw_weight = float(formula_cfg.get("raw_weight", 0.70))
        norm_weight = float(formula_cfg.get("normalized_weight", 0.30))
        insuff_threshold = float(formula_cfg.get("insufficient_info_completeness_threshold", 35.0))

        total_score = round(
            min(100.0, (raw_weight * raw_score) + (norm_weight * normalized_known_score)),
            1,
        )

        # Determine Priority Tier
        thresholds = self.kpi_config.get("priority_thresholds", {})
        high_min_score = float(thresholds.get("high_min_score", 70.0))
        high_min_comp = float(thresholds.get("high_min_completeness", 50.0))
        medium_min_score = float(thresholds.get("medium_min_score", 45.0))

        has_core_prop_type = breakdowns["property_types"].effective_points >= 12.0
        has_berlin = breakdowns["berlin_presence"].effective_points >= 10.0

        if data_completeness < insuff_threshold or (not has_berlin and not company.property_types):
            priority = LeadPriority.INSUFFICIENT_INFORMATION
        elif (
            total_score >= high_min_score
            and data_completeness >= high_min_comp
            and has_core_prop_type
            and has_berlin
        ):
            priority = LeadPriority.HIGH
        elif total_score >= medium_min_score and has_berlin:
            priority = LeadPriority.MEDIUM
        else:
            priority = LeadPriority.LOW

        # Determine Confidence Level
        if data_completeness >= 75.0:
            confidence = "High"
        elif data_completeness >= 50.0:
            confidence = "Medium"
        else:
            confidence = "Low"

        reason = self._build_qualification_explanation(
            company=company,
            breakdowns=breakdowns,
            raw_score=raw_score,
            normalized_score=normalized_known_score,
            total_score=total_score,
            priority=priority,
            completeness=data_completeness,
        )

        return LeadQualification(
            company_id=company.company_id,
            company_name=company.company_name,
            individual_kpi_scores=breakdowns,
            raw_score=round(raw_score, 1),
            normalized_known_score=normalized_known_score,
            total_score=total_score,
            lead_priority=priority,
            qualification_reason=reason,
            data_completeness=data_completeness,
            confidence=confidence,
            scoring_version=self.scoring_version,
        )

    def _score_berlin_presence(
        self, company: Company, ev_by_field: Dict[str, List[str]]
    ) -> KPIScoreBreakdown:
        max_pts = 15.0
        ev_ids = ev_by_field.get("berlin_presence", []) + ev_by_field.get("discovery_snippet", [])
        plz = (company.postal_code or "").strip()
        city = (company.city or "").lower()
        pres = (company.berlin_presence or "").lower()
        cov = [c.lower() for c in company.geographic_coverage]

        is_berlin_plz = len(plz) == 5 and plz.startswith(("10", "12", "13", "14"))
        if is_berlin_plz or city == "berlin" or "berlin" in pres:
            return KPIScoreBreakdown(
                kpi_name="berlin_presence",
                max_score=max_pts,
                awarded_score=15.0,
                effective_points=15.0,
                is_known=True,
                rationale=f"Verified presence in Berlin (PLZ: {plz or 'N/A'}, City: {company.city or 'Berlin'}).",
                supporting_evidence_ids=ev_ids[:3],
            )
        if any(r in cov for r in ("berlin", "potsdam", "brandenburg")):
            return KPIScoreBreakdown(
                kpi_name="berlin_presence",
                max_score=max_pts,
                awarded_score=10.0,
                effective_points=10.0,
                is_known=True,
                rationale="Operates in Greater Berlin / Brandenburg region.",
                supporting_evidence_ids=ev_ids[:3],
            )
        if not company.city and not company.postal_code and not company.berlin_presence:
            return KPIScoreBreakdown(
                kpi_name="berlin_presence",
                max_score=max_pts,
                awarded_score=None,
                effective_points=0.0,
                is_known=False,
                rationale="Location and geographic coverage could not be verified.",
            )
        return KPIScoreBreakdown(
            kpi_name="berlin_presence",
            max_score=max_pts,
            awarded_score=0.0,
            effective_points=0.0,
            is_known=True,
            rationale="No evidence of operational coverage in Berlin.",
        )

    def _score_property_types(
        self, company: Company, ev_by_field: Dict[str, List[str]]
    ) -> KPIScoreBreakdown:
        max_pts = 20.0
        ev_ids = ev_by_field.get("property_types", []) + ev_by_field.get("services", [])
        joined = " ".join(company.property_types + company.services).lower()

        if not joined.strip():
            return KPIScoreBreakdown(
                kpi_name="property_types",
                max_score=max_pts,
                awarded_score=None,
                effective_points=0.0,
                is_known=False,
                rationale="Managed property types are not specified on public pages.",
            )

        has_weg = "weg" in joined or "wohnungseigentum" in joined
        has_miet = "mietverwaltung" in joined or "zinshaus" in joined or "mietshaus" in joined or "wohnimmobilien" in joined
        has_gewerbe_or_sev = "gewerbe" in joined or "sondereigentum" in joined or "sev" in joined

        if has_weg and has_miet:
            return KPIScoreBreakdown(
                kpi_name="property_types",
                max_score=max_pts,
                awarded_score=20.0,
                effective_points=20.0,
                is_known=True,
                rationale="Manages both WEG (condominiums) and Mietverwaltung (multi-family residential), ideal for submetering.",
                supporting_evidence_ids=ev_ids[:3],
            )
        if has_weg or has_miet:
            which = "WEG-Verwaltung" if has_weg else "Mietverwaltung"
            return KPIScoreBreakdown(
                kpi_name="property_types",
                max_score=max_pts,
                awarded_score=16.0,
                effective_points=16.0,
                is_known=True,
                rationale=f"Core multi-unit residential management verified ({which}).",
                supporting_evidence_ids=ev_ids[:3],
            )
        if has_gewerbe_or_sev or "hausverwaltung" in joined or "immobilienverwaltung" in joined:
            return KPIScoreBreakdown(
                kpi_name="property_types",
                max_score=max_pts,
                awarded_score=12.0,
                effective_points=12.0,
                is_known=True,
                rationale="Offers commercial, SEV, or general property administration.",
                supporting_evidence_ids=ev_ids[:3],
            )
        return KPIScoreBreakdown(
            kpi_name="property_types",
            max_score=max_pts,
            awarded_score=0.0,
            effective_points=0.0,
            is_known=True,
            rationale="Only non-management real estate activities (e.g., brokerage) detected.",
        )

    def _score_metering_relevance(
        self, company: Company, ev_by_field: Dict[str, List[str]]
    ) -> KPIScoreBreakdown:
        max_pts = 20.0
        ev_ids = ev_by_field.get("services", []) + ev_by_field.get("metering_relevance", [])
        combined = " ".join(
            company.services
            + company.metering_signals
            + [company.metering_relevance or "", company.description or ""]
        ).lower()

        if not combined.strip():
            return KPIScoreBreakdown(
                kpi_name="metering_relevance",
                max_score=max_pts,
                awarded_score=None,
                effective_points=0.0,
                is_known=False,
                rationale="Insufficient service descriptions to evaluate metering/billing relevance.",
            )

        billing_kws = (
            "heizkosten",
            "betriebskosten",
            "nebenkosten",
            "hausgeldabrechnung",
            "jahresabrechnung",
            "messdienst",
            "rauchwarnmelder",
            "verbrauchs",
        )
        erp_digital_kws = (
            "casavi",
            "domus",
            "wodis",
            "immoware",
            "haufe",
            "powerhaus",
            "karthago",
            "kundenportal",
            "eigentümerportal",
            "mieterportal",
            "online-portal",
            "digital",
        )
        tech_kws = ("technische verwaltung", "technische gebäude", "instandhaltung", "haustechnik", "modernisierung")

        has_billing = any(k in combined for k in billing_kws)
        has_erp = any(k in combined for k in erp_digital_kws)
        has_tech = any(k in combined for k in tech_kws)

        if has_billing and has_erp:
            return KPIScoreBreakdown(
                kpi_name="metering_relevance",
                max_score=max_pts,
                awarded_score=20.0,
                effective_points=20.0,
                is_known=True,
                rationale="Strong fit: explicitly handles utility/heating billing AND uses digital portals/ERP systems.",
                supporting_evidence_ids=ev_ids[:3],
            )
        if has_billing or has_tech:
            return KPIScoreBreakdown(
                kpi_name="metering_relevance",
                max_score=max_pts,
                awarded_score=15.0,
                effective_points=15.0,
                is_known=True,
                rationale="Explicitly offers utility/Hausgeld billing or technical building management.",
                supporting_evidence_ids=ev_ids[:3],
            )
        if company.property_types or company.services:
            return KPIScoreBreakdown(
                kpi_name="metering_relevance",
                max_score=max_pts,
                awarded_score=10.0,
                effective_points=10.0,
                is_known=True,
                rationale="Standard property management portfolio requiring annual HKVO utility billing.",
                supporting_evidence_ids=ev_ids[:3],
            )
        return KPIScoreBreakdown(
            kpi_name="metering_relevance",
            max_score=max_pts,
            awarded_score=0.0,
            effective_points=0.0,
            is_known=True,
            rationale="No metering or billing relevance detected.",
        )

    def _score_managed_units(
        self, company: Company, ev_by_field: Dict[str, List[str]]
    ) -> KPIScoreBreakdown:
        max_pts = 15.0
        total_units = company.effective_total_units()
        ev_ids = (
            ev_by_field.get("managed_residential_units", [])
            + ev_by_field.get("managed_commercial_units", [])
            + ev_by_field.get("managed_total_units", [])
        )

        if total_units is None:
            return KPIScoreBreakdown(
                kpi_name="managed_units",
                max_score=max_pts,
                awarded_score=None,
                effective_points=0.0,
                is_known=False,
                rationale="Managed unit count is not publicly disclosed on website (neutral handling applied).",
            )

        if total_units >= 2000:
            pts = 15.0
        elif total_units >= 500:
            pts = 12.0
        elif total_units >= 100:
            pts = 9.0
        elif total_units >= 10:
            pts = 5.0
        elif total_units >= 1:
            pts = 2.0
        else:
            pts = 0.0

        return KPIScoreBreakdown(
            kpi_name="managed_units",
            max_score=max_pts,
            awarded_score=pts,
            effective_points=pts,
            is_known=True,
            rationale=f"Verified portfolio of {total_units:,} managed units.",
            supporting_evidence_ids=ev_ids[:3],
        )

    def _score_managed_buildings(
        self, company: Company, ev_by_field: Dict[str, List[str]]
    ) -> KPIScoreBreakdown:
        max_pts = 10.0
        buildings = company.managed_buildings
        ev_ids = ev_by_field.get("managed_buildings", [])

        if buildings is None:
            return KPIScoreBreakdown(
                kpi_name="managed_buildings",
                max_score=max_pts,
                awarded_score=None,
                effective_points=0.0,
                is_known=False,
                rationale="Managed building/object count is not publicly disclosed (neutral handling applied).",
            )

        if buildings >= 50:
            pts = 10.0
        elif buildings >= 20:
            pts = 8.0
        elif buildings >= 5:
            pts = 5.0
        elif buildings >= 1:
            pts = 2.0
        else:
            pts = 0.0

        return KPIScoreBreakdown(
            kpi_name="managed_buildings",
            max_score=max_pts,
            awarded_score=pts,
            effective_points=pts,
            is_known=True,
            rationale=f"Verified portfolio of {buildings:,} managed buildings/properties.",
            supporting_evidence_ids=ev_ids[:3],
        )

    def _score_decision_makers(
        self, company: Company, contacts: List[Contact]
    ) -> KPIScoreBreakdown:
        max_pts = 10.0
        comp_contacts = [c for c in contacts if c.company_id == company.company_id]

        if comp_contacts:
            has_tier12 = any(c.role_priority_tier in (1, 2) for c in comp_contacts)
            has_direct_channel = any(
                (
                    c.professional_email
                    and not c.is_generic_email
                    and c.email_status
                    in (
                        EmailStatus.PUBLICLY_PUBLISHED,
                        EmailStatus.TECHNICALLY_DELIVERABILITY_CHECKED,
                    )
                )
                or bool(c.linkedin_url)
                for c in comp_contacts
            )
            names_preview = ", ".join(f"{c.full_name} ({c.position})" for c in comp_contacts[:2])
            if has_tier12 and has_direct_channel:
                return KPIScoreBreakdown(
                    kpi_name="decision_makers",
                    max_score=max_pts,
                    awarded_score=10.0,
                    effective_points=10.0,
                    is_known=True,
                    rationale=f"Named decision-maker(s) with direct professional email/LinkedIn: {names_preview}.",
                )
            return KPIScoreBreakdown(
                kpi_name="decision_makers",
                max_score=max_pts,
                awarded_score=7.0,
                effective_points=7.0,
                is_known=True,
                rationale=f"Named decision-maker(s) identified ({names_preview}) with company contact channel.",
            )

        if company.general_email or company.phone:
            return KPIScoreBreakdown(
                kpi_name="decision_makers",
                max_score=max_pts,
                awarded_score=3.0,
                effective_points=3.0,
                is_known=True,
                rationale="Only generic company contact details found; no individual decision-maker extracted.",
            )

        return KPIScoreBreakdown(
            kpi_name="decision_makers",
            max_score=max_pts,
            awarded_score=0.0,
            effective_points=0.0,
            is_known=True,
            rationale="No decision-makers or contact details available.",
        )

    def _score_company_size(
        self, company: Company, ev_by_field: Dict[str, List[str]]
    ) -> KPIScoreBreakdown:
        max_pts = 5.0
        emp = company.employee_count
        ev_ids = ev_by_field.get("employee_count", [])

        if emp is None:
            return KPIScoreBreakdown(
                kpi_name="company_size",
                max_score=max_pts,
                awarded_score=None,
                effective_points=0.0,
                is_known=False,
                rationale="Employee headcount is not publicly disclosed (neutral handling applied).",
            )

        if emp >= 20:
            pts = 5.0
        elif emp >= 5:
            pts = 3.0
        else:
            pts = 1.0

        return KPIScoreBreakdown(
            kpi_name="company_size",
            max_score=max_pts,
            awarded_score=pts,
            effective_points=pts,
            is_known=True,
            rationale=f"Verified team size of {emp} employees.",
            supporting_evidence_ids=ev_ids[:2],
        )

    def _score_growth_signals(
        self, company: Company, ev_by_field: Dict[str, List[str]]
    ) -> KPIScoreBreakdown:
        max_pts = 5.0
        signals = company.growth_signals
        ev_ids = ev_by_field.get("growth_signals", [])

        if not signals and not company.services and not company.property_types:
            return KPIScoreBreakdown(
                kpi_name="growth_signals",
                max_score=max_pts,
                awarded_score=None,
                effective_points=0.0,
                is_known=False,
                rationale="Insufficient website content to assess growth/modernization signals.",
            )

        count = len(signals)
        if count >= 2:
            return KPIScoreBreakdown(
                kpi_name="growth_signals",
                max_score=max_pts,
                awarded_score=5.0,
                effective_points=5.0,
                is_known=True,
                rationale=f"Multiple growth/modernization signals: {', '.join(signals[:4])}.",
                supporting_evidence_ids=ev_ids[:2],
            )
        if count == 1:
            return KPIScoreBreakdown(
                kpi_name="growth_signals",
                max_score=max_pts,
                awarded_score=3.0,
                effective_points=3.0,
                is_known=True,
                rationale=f"Growth/modernization signal detected: {signals[0]}.",
                supporting_evidence_ids=ev_ids[:2],
            )
        return KPIScoreBreakdown(
            kpi_name="growth_signals",
            max_score=max_pts,
            awarded_score=0.0,
            effective_points=0.0,
            is_known=True,
            rationale="No explicit expansion, hiring, or association signals observed.",
        )

    @staticmethod
    def _build_qualification_explanation(
        company: Company,
        breakdowns: Dict[str, KPIScoreBreakdown],
        raw_score: float,
        normalized_score: float,
        total_score: float,
        priority: LeadPriority,
        completeness: float,
    ) -> str:
        """Construct a transparent, sales-ready summary of the deterministic qualification."""
        parts: List[str] = [
            f"[{priority.value} Priority | Score: {total_score}/100 (Raw: {raw_score:.1f}, Known-Normalized: {normalized_score:.1f}) | Completeness: {completeness:.0f}%]"
        ]
        for key in (
            "berlin_presence",
            "property_types",
            "metering_relevance",
            "managed_units",
            "managed_buildings",
            "decision_makers",
        ):
            b = breakdowns[key]
            status_str = f"{b.effective_points:.0f}/{b.max_score:.0f} pts" if b.is_known else "Unknown (Neutral)"
            parts.append(f"{key}: {status_str} ({b.rationale})")

        return " | ".join(parts)
