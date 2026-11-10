"""CLI Entrypoint & Pipeline Orchestrator for the Heidi Systems B2B Lead Generation System."""

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from src.config import Settings, get_settings
from src.models import CrawlStatus
from src.services.ai_extractor import AIExtractorService
from src.services.contact_research import ContactResearchService
from src.services.discovery import DiscoveryService
from src.services.exporter import ExportService
from src.services.qualification import LeadQualificationService
from src.services.validation import ValidationService
from src.services.website_extractor import WebsiteExtractorService
from src.storage.repository import LeadRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("heidi.pipeline")


class HeidiLeadPipeline:
    """Orchestrates discovery, website crawling, AI extraction, contact research, KPI qualification, and Excel export."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        kpi_cfg = self.settings.load_kpi_config()
        excluded_domains = kpi_cfg.get("discovery", {}).get("excluded_domains", [])

        self.repository = LeadRepository(self.settings)
        self.validator = ValidationService(excluded_domains=excluded_domains)
        self.discovery_service = DiscoveryService(self.settings, self.validator)
        self.website_extractor = WebsiteExtractorService(self.settings)
        self.ai_extractor = AIExtractorService(self.settings, self.validator)
        self.contact_service = ContactResearchService(
            self.settings, llm=self.ai_extractor.llm
        )
        self.qualification_service = LeadQualificationService(self.settings)
        self.export_service = ExportService(self.settings)

    def run_discovery_stage(self, max_companies: int = 25) -> int:
        """Stage 1: Discover Berlin property management companies and persist unique records."""
        logger.info("=== STAGE 1: Company Discovery (max_companies=%d) ===", max_companies)
        companies, evidences = self.discovery_service.discover_companies(
            max_companies=max_companies
        )
        # Merge with any existing companies in repository
        existing = self.repository.list_companies(include_samples=False)
        merged = self.validator.deduplicate_companies(existing + companies)
        if max_companies and len(merged) > max_companies:
            merged = merged[:max_companies]

        for comp in merged:
            self.repository.upsert_company(comp)
        for ev in evidences:
            self.repository.add_evidence(ev)

        self.repository.save_all()
        logger.info("Stage 1 complete: %d unique companies saved.", len(merged))
        return len(merged)

    def run_enrichment_and_contacts_stage(self, force_refresh: bool = False) -> int:
        """Stages 2, 3 & 5: Crawl company websites, run DeepSeek extraction, and research contacts."""
        companies = self.repository.list_companies(include_samples=False)
        logger.info("=== STAGE 2 & 3 & 5: Website Crawl, AI Extraction & Contact Research (%d companies) ===", len(companies))
        processed = 0

        for idx, comp in enumerate(companies, start=1):
            if (
                not force_refresh
                and comp.crawl_status == CrawlStatus.SUCCESS
                and (comp.services or comp.property_types)
            ):
                logger.info(
                    "[%d/%d] Skipping already enriched company: %s",
                    idx,
                    len(companies),
                    comp.company_name,
                )
                continue

            logger.info(
                "[%d/%d] Crawling & analyzing: %s (%s)",
                idx,
                len(companies),
                comp.company_name,
                comp.website,
            )
            crawl = self.website_extractor.crawl_company_website(comp.website)
            enriched_comp, comp_evidences = self.ai_extractor.enrich_company_from_crawl(
                comp, crawl
            )
            contacts, contact_evidences = self.contact_service.research_contacts(
                enriched_comp, crawl
            )

            self.repository.upsert_company(enriched_comp)
            for ev in comp_evidences + contact_evidences:
                self.repository.add_evidence(ev)
            for ct in contacts:
                self.repository.add_contact(ct)

            # Save incrementally after every company for crash recovery
            self.repository.save_all()
            processed += 1

        logger.info("Enrichment & contact research complete (%d companies processed).", processed)
        return processed

    def run_qualification_stage(self) -> int:
        """Stage 4: Run deterministic KPI scoring across all discovered companies."""
        companies = self.repository.list_companies(include_samples=False)
        all_evidence = self.repository.list_evidence()
        all_contacts = self.repository.list_contacts()

        logger.info("=== STAGE 4: Deterministic KPI Lead Qualification (%d companies) ===", len(companies))
        for comp in companies:
            qual = self.qualification_service.qualify_company(
                company=comp,
                evidences=all_evidence,
                contacts=all_contacts,
            )
            self.repository.upsert_qualification(qual)

        self.repository.save_all()
        logger.info("Qualification complete for %d companies.", len(companies))
        return len(companies)

    def run_export_stage(self, output_filename: str = "heidi_berlin_leads.xlsx") -> Path:
        """Stage 6 & 7: Final deduplication check and 5-sheet Excel workbook generation."""
        companies = self.repository.list_companies(include_samples=False)
        qualifications = self.repository.list_qualifications()
        contacts = self.repository.list_contacts()
        evidences = self.repository.list_evidence()

        logger.info("=== STAGE 7: Generating 5-Sheet Excel Deliverable (%s) ===", output_filename)
        excel_path = self.export_service.export_to_excel(
            companies=companies,
            qualifications=qualifications,
            contacts=contacts,
            evidences=evidences,
            output_filename=output_filename,
        )
        return excel_path

    def run_full_pipeline(
        self,
        max_companies: int = 25,
        force_refresh: bool = False,
        output_filename: str = "heidi_berlin_leads.xlsx",
    ) -> Dict[str, object]:
        """Run all stages end-to-end and return summary statistics."""
        self.run_discovery_stage(max_companies=max_companies)
        self.run_enrichment_and_contacts_stage(force_refresh=force_refresh)
        self.run_qualification_stage()
        excel_path = self.run_export_stage(output_filename=output_filename)

        companies = self.repository.list_companies(include_samples=False)
        qualifications = self.repository.list_qualifications()
        contacts = self.repository.list_contacts()
        evidences = self.repository.list_evidence()

        priority_counts: Dict[str, int] = {}
        for q in qualifications:
            priority_counts[q.lead_priority.value] = priority_counts.get(q.lead_priority.value, 0) + 1

        summary = {
            "total_companies": len(companies),
            "total_qualifications": len(qualifications),
            "priority_breakdown": priority_counts,
            "total_contacts": len(contacts),
            "total_evidence_records": len(evidences),
            "excel_path": str(excel_path.resolve()),
        }
        logger.info("Pipeline Summary: %s", summary)
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Heidi Systems AI-Powered B2B Lead Generation Pipeline (Berlin Hausverwaltungen)"
    )
    parser.add_argument(
        "--stage",
        choices=["all", "discover", "enrich", "qualify", "export"],
        default="all",
        help="Pipeline stage to execute (default: all)",
    )
    parser.add_argument(
        "--max-companies",
        type=int,
        default=25,
        help="Maximum number of unique Berlin property management companies to process (default: 25)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-crawl and re-extract companies even if already cached in repository",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="heidi_berlin_leads.xlsx",
        help="Output Excel workbook filename in data/output/",
    )

    args = parser.parse_args()
    pipeline = HeidiLeadPipeline()

    if args.stage == "all":
        pipeline.run_full_pipeline(
            max_companies=args.max_companies,
            force_refresh=args.force_refresh,
            output_filename=args.output,
        )
    elif args.stage == "discover":
        pipeline.run_discovery_stage(max_companies=args.max_companies)
    elif args.stage == "enrich":
        pipeline.run_enrichment_and_contacts_stage(force_refresh=args.force_refresh)
    elif args.stage == "qualify":
        pipeline.run_qualification_stage()
    elif args.stage == "export":
        pipeline.run_export_stage(output_filename=args.output)


if __name__ == "__main__":
    main()
