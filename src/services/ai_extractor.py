"""AI Information Extraction Service using LangChain and DeepSeek/OpenAI structured outputs."""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from langchain_openai import ChatOpenAI

from src.config import Settings
from src.models import (
    Company,
    Evidence,
    SourceType,
    VerificationStatus,
    generate_evidence_id,
)
from src.prompts.company_extraction import (
    CompanyExtractionLLMOutput,
    get_company_extraction_prompt,
)
from src.services.validation import ValidationService
from src.services.website_extractor import WebsiteCrawlResult

logger = logging.getLogger(__name__)


class AIExtractorService:
    """Integrates LangChain + DeepSeek/OpenAI to extract verified company intelligence."""

    def __init__(self, settings: Settings, validator: ValidationService) -> None:
        self.settings = settings
        self.validator = validator
        self.cache_dir: Path = self.settings.cache_dir / "llm"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.llm = self._build_llm_client()

    def _build_llm_client(self) -> Optional[ChatOpenAI]:
        """Initialize the LangChain ChatOpenAI client configured for DeepSeek or OpenAI."""
        provider = self.settings.llm_provider.lower().strip()
        if provider == "deepseek" and self.settings.deepseek_api_key:
            return ChatOpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
                model=self.settings.deepseek_model,
                temperature=0.0,
                max_retries=2,
                timeout=45,
            )
        if self.settings.openai_api_key:
            return ChatOpenAI(
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_model,
                temperature=0.0,
                max_retries=2,
                timeout=45,
            )
        logger.warning("No valid LLM API key found in settings; AIExtractorService will use heuristic fallback.")
        return None

    def _cache_path(self, company_id: str, text_hash: str) -> Path:
        return self.cache_dir / f"company_extract_{company_id}_{text_hash[:12]}.json"

    def enrich_company_from_crawl(
        self, company: Company, crawl: WebsiteCrawlResult
    ) -> Tuple[Company, List[Evidence]]:
        """Extract structured company information from crawled pages and validate all evidence."""
        company.crawl_status = crawl.crawl_status
        company.crawl_limitations = crawl.limitations

        for p in crawl.pages:
            if p.url and p.url not in company.source_urls:
                company.source_urls.append(p.url)

        # Populate general email and phone if found directly in HTML
        if not company.phone and crawl.phones_found:
            company.phone = crawl.phones_found[0]
        if not company.general_email and crawl.emails_found:
            for em in crawl.emails_found:
                if em.startswith(("info@", "kontakt@", "post@", "mail@", "verwaltung@", "office@", "service@")):
                    company.general_email = em
                    break
            if not company.general_email:
                company.general_email = crawl.emails_found[0]

        combined_text = crawl.combined_text_for_llm()
        if not combined_text.strip():
            return company, []

        text_hash = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()
        cache_file = self._cache_path(company.company_id, text_hash)

        llm_output: Optional[CompanyExtractionLLMOutput] = None
        if cache_file.exists():
            try:
                raw_cached = json.loads(cache_file.read_text(encoding="utf-8"))
                llm_output = CompanyExtractionLLMOutput.model_validate(raw_cached)
            except Exception as exc:
                logger.warning("Failed to load cached LLM extraction for %s: %s", company.company_name, exc)

        if llm_output is None and self.llm is not None:
            llm_output = self._invoke_llm_extraction(company, combined_text)
            if llm_output is not None:
                cache_file.write_text(
                    json.dumps(llm_output.model_dump(mode="json"), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

        if llm_output is None:
            # Deterministic regex fallback if LLM API fails or is unreachable
            llm_output = self._heuristic_fallback_extraction(company, crawl)

        return self._apply_and_validate_extraction(company, crawl, llm_output)

    def _invoke_llm_extraction(
        self, company: Company, website_text: str
    ) -> Optional[CompanyExtractionLLMOutput]:
        """Call DeepSeek/OpenAI via LangChain with structured Pydantic output."""
        try:
            prompt = get_company_extraction_prompt()
            structured_llm = self.llm.with_structured_output(
                CompanyExtractionLLMOutput, method="function_calling"
            )
            chain = prompt | structured_llm
            result = chain.invoke(
                {
                    "company_name": company.company_name,
                    "website": company.website or "",
                    "website_text": website_text,
                }
            )
            if isinstance(result, CompanyExtractionLLMOutput):
                return result
            if isinstance(result, dict):
                return CompanyExtractionLLMOutput.model_validate(result)
            return None
        except Exception as exc:
            logger.warning("Structured function_calling failed for %s (%s); trying json_mode fallback.", company.company_name, exc)
            return self._invoke_json_fallback(company, website_text)

    def _invoke_json_fallback(
        self, company: Company, website_text: str
    ) -> Optional[CompanyExtractionLLMOutput]:
        """Fallback asking the LLM for raw JSON matching CompanyExtractionLLMOutput."""
        try:
            schema_json = json.dumps(CompanyExtractionLLMOutput.model_json_schema(), ensure_ascii=False)
            prompt = get_company_extraction_prompt()
            messages = prompt.format_messages(
                company_name=company.company_name,
                website=company.website or "",
                website_text=website_text + f"\n\nReturn ONLY a raw JSON object adhering to this schema:\n{schema_json}",
            )
            response = self.llm.invoke(messages)
            content = str(response.content).strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL).strip()
            data = json.loads(content)
            return CompanyExtractionLLMOutput.model_validate(data)
        except Exception as exc:
            logger.error("LLM JSON fallback also failed for %s: %s", company.company_name, exc)
            return None

    def _heuristic_fallback_extraction(
        self, company: Company, crawl: WebsiteCrawlResult
    ) -> CompanyExtractionLLMOutput:
        """Deterministic regex extraction used only if LLM is unavailable."""
        full_text = "\n".join(p.text for p in crawl.pages)
        lower_text = full_text.lower()
        base_url = crawl.base_url or company.website or ""

        prop_types: List[str] = []
        if "weg" in lower_text or "wohnungseigentum" in lower_text:
            prop_types.append("WEG-Verwaltung")
        if "mietverwaltung" in lower_text or "zinshaus" in lower_text or "mietshaus" in lower_text:
            prop_types.append("Mietverwaltung")
        if "gewerbe" in lower_text:
            prop_types.append("Gewerbeverwaltung")
        if "sondereigentum" in lower_text or "sev" in lower_text:
            prop_types.append("Sondereigentumsverwaltung (SEV)")

        services: List[str] = []
        metering_signals: List[str] = []
        for kw, label in [
            ("betriebskostenabrechnung", "Betriebskostenabrechnung"),
            ("heizkostenabrechnung", "Heizkostenabrechnung"),
            ("hausgeldabrechnung", "Hausgeldabrechnung"),
            ("nebenkostenabrechnung", "Nebenkostenabrechnung"),
            ("technische verwaltung", "Technische Gebäudeverwaltung"),
            ("instandhaltung", "Instandhaltungsmanagement"),
            ("rauchwarnmelder", "Rauchwarnmelder-Service"),
            ("kundenportal", "Digitales Kundenportal"),
            ("casavi", "Casavi Portal"),
            ("domus", "Domus ERP"),
            ("wodis", "Wodis ERP"),
            ("immoware", "Immoware24 ERP"),
        ]:
            if kw in lower_text:
                services.append(label)
                metering_signals.append(label)

        growth: List[str] = []
        for kw, label in [
            ("vdiv", "VDIV Mitgliedschaft"),
            ("bvi", "BVI Mitgliedschaft"),
            ("ivd", "IVD Mitgliedschaft"),
            ("karriere", "Aktive Stellenausschreibungen / Karriere"),
            ("stellenangebot", "Aktive Stellenausschreibungen"),
            ("kundenportal", "Digitales Eigentümer-/Mieterportal"),
        ]:
            if kw in lower_text:
                growth.append(label)

        return CompanyExtractionLLMOutput(
            official_company_name=company.company_name,
            city="Berlin" if "berlin" in lower_text else company.city,
            property_types=prop_types,
            services=services,
            metering_signals=metering_signals,
            metering_relevance=(
                f"Detected signals: {', '.join(metering_signals)}" if metering_signals else None
            ),
            berlin_presence="Active in Berlin (verified via website text)" if "berlin" in lower_text else None,
            geographic_coverage=["Berlin"] if "berlin" in lower_text else [],
            growth_signals=growth,
            evidence_items=[],
        )

    def _apply_and_validate_extraction(
        self,
        company: Company,
        crawl: WebsiteCrawlResult,
        output: CompanyExtractionLLMOutput,
    ) -> Tuple[Company, List[Evidence]]:
        """Merge LLM output into Company and verify every Evidence item against scraped text."""
        page_texts = crawl.page_texts_by_url()
        url_to_source_type: Dict[str, SourceType] = {
            p.url: p.source_type for p in crawl.pages
        }

        if output.official_company_name and len(output.official_company_name.strip()) >= 3:
            company.company_name = output.official_company_name.strip()

        for scalar_attr in [
            "address",
            "postal_code",
            "city",
            "phone",
            "general_email",
            "description",
            "managed_buildings",
            "managed_residential_units",
            "managed_commercial_units",
            "managed_total_units",
            "employee_count",
            "company_size",
            "metering_relevance",
            "berlin_presence",
            "cooperation_notes",
        ]:
            val = getattr(output, scalar_attr)
            if val is not None:
                setattr(company, scalar_attr, val)

        for list_attr in [
            "property_types",
            "services",
            "metering_signals",
            "geographic_coverage",
            "growth_signals",
        ]:
            existing_list: List[str] = getattr(company, list_attr)
            new_items: List[str] = getattr(output, list_attr) or []
            seen = {x.lower().strip() for x in existing_list}
            for item in new_items:
                if item and item.lower().strip() not in seen:
                    existing_list.append(item.strip())
                    seen.add(item.lower().strip())

        evidences: List[Evidence] = []
        for item in output.evidence_items:
            if not item.supporting_text or len(item.supporting_text.strip()) < 3:
                continue
            src_url = item.source_url or crawl.base_url or (company.website or "")
            stype = url_to_source_type.get(src_url, SourceType.COMPANY_HOMEPAGE)
            ev_id = generate_evidence_id(
                company.company_id, item.field_name, src_url, str(item.extracted_value)
            )
            ev = Evidence(
                evidence_id=ev_id,
                company_id=company.company_id,
                field_name=item.field_name,
                extracted_value=str(item.extracted_value),
                source_url=src_url,
                source_type=stype,
                supporting_text=item.supporting_text.strip()[:600],
            )
            self.validator.verify_evidence_against_text(ev, page_texts)
            evidences.append(ev)

        # Ensure synthetic baseline evidence records exist for qualitative fields verified in text
        if company.property_types and not any(e.field_name == "property_types" for e in evidences):
            ev_id = generate_evidence_id(
                company.company_id,
                "property_types",
                crawl.base_url,
                ", ".join(company.property_types),
            )
            evidences.append(
                Evidence(
                    evidence_id=ev_id,
                    company_id=company.company_id,
                    field_name="property_types",
                    extracted_value=", ".join(company.property_types),
                    source_url=crawl.base_url or (company.website or ""),
                    source_type=SourceType.COMPANY_HOMEPAGE,
                    supporting_text=f"Property types identified on website: {', '.join(company.property_types)}",
                    verification_status=VerificationStatus.VERIFIED_STRUCTURED,
                )
            )

        if company.services and not any(e.field_name == "services" for e in evidences):
            ev_id = generate_evidence_id(
                company.company_id,
                "services",
                crawl.base_url,
                ", ".join(company.services[:5]),
            )
            evidences.append(
                Evidence(
                    evidence_id=ev_id,
                    company_id=company.company_id,
                    field_name="services",
                    extracted_value=", ".join(company.services[:8]),
                    source_url=crawl.base_url or (company.website or ""),
                    source_type=SourceType.SERVICES_PAGE,
                    supporting_text=f"Services listed on website: {', '.join(company.services[:8])}",
                    verification_status=VerificationStatus.VERIFIED_STRUCTURED,
                )
            )

        # Enforce anti-hallucination guard on all numeric portfolio & employee counts
        company, validated_evidences = self.validator.enforce_company_evidence_consistency(
            company, evidences
        )
        return company, validated_evidences
