"""Contact Research Service for extracting and verifying publicly listed decision-makers."""

import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Dict, List, Optional, Set, Tuple

import dns.resolver
from langchain_openai import ChatOpenAI

from src.config import Settings
from src.models import (
    Company,
    Contact,
    EmailStatus,
    Evidence,
    SourceType,
    VerificationStatus,
    generate_contact_id,
    generate_evidence_id,
)
from src.prompts.contact_extraction import (
    ContactExtractionLLMOutput,
    ExtractedContactItem,
    get_contact_extraction_prompt,
)
from src.services.website_extractor import WebsiteCrawlResult

logger = logging.getLogger(__name__)

GENERIC_EMAIL_PREFIXES = (
    "info@",
    "kontakt@",
    "mail@",
    "post@",
    "office@",
    "verwaltung@",
    "hausverwaltung@",
    "service@",
    "empfang@",
    "zentrale@",
    "support@",
    "anfrage@",
    "bewerbung@",
    "datenschutz@",
)

IMPRESSUM_LEADER_PATTERNS = [
    re.compile(
        r"(?:Geschäftsführer(?:in|innen)?|Vertretungsberechtigte[r]?\s+Geschäftsführer(?:in)?|Vertreten\s+durch(?:\s+die\s+Geschäftsführer)?|Inhaber(?:in)?|Vorstand)\s*[:\-]?\s*([A-ZÄÖÜ][a-zäöüß\-\.]+(?:\s+[A-ZÄÖÜ][a-zäöüß\-\.]+){1,3})",
        re.MULTILINE,
    ),
]


class ContactResearchService:
    """Extracts decision-makers from Impressum/Team pages and performs DNS MX email verification."""

    def __init__(self, settings: Settings, llm: Optional[ChatOpenAI] = None) -> None:
        self.settings = settings
        self.cache_dir: Path = self.settings.cache_dir / "contacts"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.llm = llm or self._build_llm_client()
        self._mx_cache: Dict[str, bool] = {}

    def _build_llm_client(self) -> Optional[ChatOpenAI]:
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
        return None

    def check_domain_mx_deliverability(self, email: str) -> bool:
        """Perform a technical DNS MX / A record deliverability check on an email's domain."""
        if not email or "@" not in email:
            return False
        domain = email.split("@", 1)[1].lower().strip()
        if domain in self._mx_cache:
            return self._mx_cache[domain]

        has_mail_server = False
        try:
            answers = dns.resolver.resolve(domain, "MX", lifetime=3.0)
            has_mail_server = len(answers) > 0
        except Exception:
            try:
                answers_a = dns.resolver.resolve(domain, "A", lifetime=3.0)
                has_mail_server = len(answers_a) > 0
            except Exception:
                has_mail_server = False

        self._mx_cache[domain] = has_mail_server
        return has_mail_server

    @staticmethod
    def is_generic_mailbox(email: Optional[str]) -> bool:
        """Return True if an email address is a generic role mailbox like info@ or kontakt@."""
        if not email:
            return False
        lower = email.lower().strip()
        return lower.startswith(GENERIC_EMAIL_PREFIXES)

    def determine_email_status(
        self,
        email: Optional[str],
        published_emails_on_site: Set[str],
    ) -> EmailStatus:
        """Strictly classify email verification status according to compliance rules."""
        if not email or not email.strip():
            return EmailStatus.NOT_FOUND

        clean_email = email.lower().strip()
        # Ensure we NEVER accept an email that was not actually published on the site
        if clean_email not in published_emails_on_site:
            return EmailStatus.UNVERIFIED

        # Check DNS MX deliverability of the published email
        if self.check_domain_mx_deliverability(clean_email):
            return EmailStatus.TECHNICALLY_DELIVERABILITY_CHECKED
        return EmailStatus.PUBLICLY_PUBLISHED

    def research_contacts(
        self, company: Company, crawl: WebsiteCrawlResult
    ) -> Tuple[List[Contact], List[Evidence]]:
        """Extract and verify decision-makers from crawled website pages."""
        if not crawl.pages:
            return [], []

        published_emails: Set[str] = {e.lower().strip() for e in crawl.emails_found}
        if company.general_email:
            published_emails.add(company.general_email.lower().strip())

        # Prioritize Impressum, Team, and Contact pages for contact extraction
        relevant_pages = [
            p
            for p in crawl.pages
            if p.source_type in (SourceType.IMPRESSUM, SourceType.TEAM_PAGE)
            or any(k in p.url.lower() for k in ("impressum", "team", "ueber", "kontakt", "unternehmen"))
        ]
        if not relevant_pages:
            relevant_pages = crawl.pages[:3]

        combined_contact_text = "\n\n".join(
            f"=== PAGE SOURCE_URL: {p.url} ===\n{p.text[:6000]}" for p in relevant_pages
        )
        text_hash = hashlib.sha256(combined_contact_text.encode("utf-8")).hexdigest()[:12]
        cache_file = self.cache_dir / f"contacts_{company.company_id}_{text_hash}.json"

        extracted_items: List[ExtractedContactItem] = []
        if cache_file.exists():
            try:
                raw = json.loads(cache_file.read_text(encoding="utf-8"))
                parsed = ContactExtractionLLMOutput.model_validate(raw)
                extracted_items = parsed.contacts
            except Exception:
                pass

        if not extracted_items and self.llm is not None and combined_contact_text.strip():
            extracted_items = self._invoke_llm_contact_extraction(
                company, combined_contact_text, list(published_emails)
            )
            if extracted_items:
                cache_file.write_text(
                    json.dumps(
                        ContactExtractionLLMOutput(contacts=extracted_items).model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

        # Supplement with deterministic regex extraction from Impressum if LLM found none
        if not extracted_items:
            extracted_items = self._regex_impressum_fallback(relevant_pages)

        contacts: List[Contact] = []
        evidences: List[Evidence] = []
        seen_names: Set[str] = set()

        # Select best personal email vs generic email from published emails
        personal_emails = [e for e in published_emails if not self.is_generic_mailbox(e)]

        for item in extracted_items:
            name_clean = item.full_name.strip()
            if len(name_clean) < 4 or name_clean.lower() in seen_names:
                continue
            # Guard against generic words mistakenly extracted as names
            if any(
                bad in name_clean.lower()
                for bad in ("hausverwaltung", "gmbh", "immobilien", "berlin", "telefon", "impressum", "unbekannt")
            ):
                continue

            seen_names.add(name_clean.lower())

            # Validate email: never keep an email that wasn't on the website
            candidate_email = item.professional_email.lower().strip() if item.professional_email else None
            if candidate_email and candidate_email not in published_emails:
                logger.warning(
                    "Discarding unverified/guessed email %s for contact %s",
                    candidate_email,
                    name_clean,
                )
                candidate_email = None

            # If no email was attached by LLM, check if a personal email matching their last name is published
            last_name = name_clean.split()[-1].lower()
            last_name_ascii = (
                last_name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
            )
            if not candidate_email and len(last_name_ascii) >= 3:
                for pe in personal_emails:
                    local_part = pe.split("@", 1)[0]
                    if last_name in local_part or last_name_ascii in local_part:
                        candidate_email = pe
                        break

            # Fallback to published company email ONLY if explicitly marked as generic
            is_generic = self.is_generic_mailbox(candidate_email)
            if not candidate_email and company.general_email:
                candidate_email = company.general_email.lower().strip()
                is_generic = True

            email_status = self.determine_email_status(candidate_email, published_emails)

            # Match LinkedIn URL if found on page
            linkedin_url = item.linkedin_url
            if not linkedin_url and crawl.linkedin_urls_found:
                for li in crawl.linkedin_urls_found:
                    if "/in/" in li.lower():
                        linkedin_url = li
                        break

            tier = self._classify_role_tier(item.position)
            src_url = item.source_url or crawl.base_url or (company.website or "")
            cid = generate_contact_id(company.company_id, name_clean, item.position)

            contact = Contact(
                contact_id=cid,
                company_id=company.company_id,
                company_name=company.company_name,
                full_name=name_clean,
                position=item.position.strip(),
                role_priority_tier=tier,
                professional_email=candidate_email,
                is_generic_email=is_generic,
                linkedin_url=linkedin_url,
                email_status=email_status,
                source_url=src_url,
                supporting_text=(item.supporting_text or f"{name_clean} - {item.position}")[:400],
            )
            contacts.append(contact)

            ev_id = generate_evidence_id(company.company_id, "decision_maker", src_url, name_clean)
            evidences.append(
                Evidence(
                    evidence_id=ev_id,
                    company_id=company.company_id,
                    field_name="decision_maker",
                    extracted_value=f"{name_clean} ({item.position})",
                    source_url=src_url,
                    source_type=SourceType.IMPRESSUM if "impressum" in src_url.lower() else SourceType.TEAM_PAGE,
                    supporting_text=(item.supporting_text or f"{name_clean} - {item.position}")[:400],
                    verification_status=VerificationStatus.VERIFIED_TEXT_MATCH,
                )
            )

        # Sort contacts by role priority tier (Tier 1 first, then personal email first)
        contacts.sort(key=lambda c: (c.role_priority_tier, c.is_generic_email))
        return contacts, evidences

    def _invoke_llm_contact_extraction(
        self, company: Company, website_text: str, detected_emails: List[str]
    ) -> List[ExtractedContactItem]:
        """Use LangChain + DeepSeek/OpenAI to extract decision-makers."""
        try:
            prompt = get_contact_extraction_prompt()
            structured_llm = self.llm.with_structured_output(
                ContactExtractionLLMOutput, method="function_calling"
            )
            chain = prompt | structured_llm
            res = chain.invoke(
                {
                    "company_name": company.company_name,
                    "website": company.website or "",
                    "detected_emails": ", ".join(detected_emails) if detected_emails else "None",
                    "website_text": website_text,
                }
            )
            if isinstance(res, ContactExtractionLLMOutput):
                return res.contacts
            if isinstance(res, dict):
                return ContactExtractionLLMOutput.model_validate(res).contacts
        except Exception as exc:
            logger.warning("Structured contact extraction fallback for %s: %s", company.company_name, exc)
            try:
                schema_json = json.dumps(ContactExtractionLLMOutput.model_json_schema(), ensure_ascii=False)
                prompt = get_contact_extraction_prompt()
                messages = prompt.format_messages(
                    company_name=company.company_name,
                    website=company.website or "",
                    detected_emails=", ".join(detected_emails) if detected_emails else "None",
                    website_text=website_text + f"\n\nReturn ONLY valid JSON matching:\n{schema_json}",
                )
                resp = self.llm.invoke(messages)
                content = str(resp.content).strip()
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL).strip()
                parsed = ContactExtractionLLMOutput.model_validate(json.loads(content))
                return parsed.contacts
            except Exception as inner_exc:
                logger.error("Contact JSON fallback failed for %s: %s", company.company_name, inner_exc)
        return []

    @staticmethod
    def _regex_impressum_fallback(pages: list) -> List[ExtractedContactItem]:
        """Deterministic regex parser for standard German Impressum 'Geschäftsführer' lines."""
        items: List[ExtractedContactItem] = []
        for p in pages:
            for pattern in IMPRESSUM_LEADER_PATTERNS:
                for match in pattern.finditer(p.text):
                    full_name = match.group(1).strip()
                    snippet = match.group(0).strip()
                    items.append(
                        ExtractedContactItem(
                            full_name=full_name,
                            position="Geschäftsführer",
                            role_priority_tier=1,
                            professional_email=None,
                            is_generic_email=False,
                            source_url=p.url,
                            supporting_text=snippet,
                        )
                    )
        return items

    @staticmethod
    def _classify_role_tier(position: str) -> int:
        pos_lower = position.lower()
        if any(
            k in pos_lower
            for k in ("geschäftsführ", "inhaber", "vorstand", "managing director", "ceo", "gesellschafter")
        ):
            return 1
        if any(
            k in pos_lower
            for k in ("technisch", "leiter", "leitung", "head of", "prokur", "operations", "bauleit")
        ):
            return 2
        return 3
