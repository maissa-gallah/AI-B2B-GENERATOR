"""Validation, normalization, deduplication, and anti-hallucination evidence checking."""

import hashlib
import logging
import re
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from src.models import (
    Company,
    Contact,
    Evidence,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

# Common German and international legal entity suffixes to strip during name normalization
LEGAL_SUFFIXES_PATTERN = re.compile(
    r"("
    r"gmbh\s*&\s*co\.?\s*kg|"
    r"ug\s*\(\s*haftungsbeschraenkt\s*\)|"
    r"ug\s*\(\s*haftungsbeschränkt\s*\)|"
    r"haftungsbeschraenkt|haftungsbeschränkt|"
    r"gesellschaft\s+mit\s+beschraenkter\s+haftung|"
    r"gesellschaft\s+mit\s+beschränkter\s+haftung|"
    r"\b(?:ggmbh|gmbh|mbh|ag|kg|ohg|gbr|ug|e\.?\s*k\.?|ek|se|ltd|inc)\b"
    r")",
    flags=re.IGNORECASE,
)

GENERIC_DESCRIPTORS_PATTERN = re.compile(
    r"\b(hausverwaltung|immobilienverwaltung|immobilienmanagement|grundstücksverwaltung|haus-\s*und\s*grundstücksverwaltung)\b",
    flags=re.IGNORECASE,
)


def extract_root_domain(url: Optional[str]) -> Optional[str]:
    """Extract normalized lowercase domain without 'www.' from a URL."""
    if not url or not isinstance(url, str):
        return None
    cleaned = url.strip()
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    try:
        parsed = urlparse(cleaned)
        host = (parsed.netloc or "").lower().strip()
        if ":" in host:
            host = host.split(":", 1)[0]
        if host.startswith("www."):
            host = host[4:]
        if not host or "." not in host:
            return None
        return host
    except Exception:
        return None


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Return a clean canonical base or page URL."""
    if not url or not isinstance(url, str):
        return None
    cleaned = url.strip()
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    try:
        parsed = urlparse(cleaned)
        if not parsed.netloc or "." not in parsed.netloc:
            return None
        scheme = "https" if parsed.scheme in ("http", "https") else "https"
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        return f"{scheme}://{netloc}{path}"
    except Exception:
        return None


def normalize_company_name(name: str) -> str:
    """Normalize a German company name for deterministic deduplication."""
    if not name:
        return ""
    text = name.lower()
    # Replace umlauts for consistent matching across spelling variants
    text = (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    # Remove legal suffixes
    text = LEGAL_SUFFIXES_PATTERN.sub(" ", text)
    # Remove punctuation
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Normalize phone numbers to digits only (standardizing +49 to 0) for matching."""
    if not phone:
        return None
    cleaned = phone.strip()
    cleaned = re.sub(r"\(\s*0\s*\)", "", cleaned)
    if cleaned.startswith("+49"):
        cleaned = "0" + cleaned[3:]
    elif cleaned.startswith("0049"):
        cleaned = "0" + cleaned[4:]
    digits = re.sub(r"\D", "", cleaned)
    return digits if len(digits) >= 6 else None


def generate_company_id(domain: Optional[str], company_name: str) -> str:
    """Generate a deterministic company ID preferring root domain over normalized name."""
    key = domain if domain else normalize_company_name(company_name)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"comp_{digest}"


class ValidationService:
    """Handles company deduplication, URL filtering, and anti-hallucination evidence checks."""

    def __init__(self, excluded_domains: Optional[List[str]] = None) -> None:
        self.excluded_domains: Set[str] = {
            d.lower().lstrip("www.") for d in (excluded_domains or [])
        }

    def is_excluded_domain(self, url_or_domain: Optional[str]) -> bool:
        """Check if a URL/domain belongs to an aggregator, portal, or social network."""
        domain = extract_root_domain(url_or_domain) or (url_or_domain or "").lower()
        if not domain:
            return True
        for excl in self.excluded_domains:
            if domain == excl or domain.endswith(f".{excl}"):
                return True
        return False

    def deduplicate_companies(self, companies: List[Company]) -> List[Company]:
        """Deduplicate and merge a list of Company records deterministically.

        Matching keys in order of precedence:
        1. Normalized root domain (`domain`).
        2. Exact normalized company name (`normalized_name`).
        3. Core distinctive brand name + matching postal code or normalized phone.
        """
        by_domain: Dict[str, Company] = {}
        by_norm_name: Dict[str, Company] = {}
        unique_companies: List[Company] = []

        for comp in companies:
            comp.domain = extract_root_domain(comp.website) or comp.domain
            comp.normalized_name = normalize_company_name(comp.company_name)

            existing: Optional[Company] = None
            if comp.domain and comp.domain in by_domain:
                existing = by_domain[comp.domain]
            elif comp.normalized_name and comp.normalized_name in by_norm_name:
                existing = by_norm_name[comp.normalized_name]
            else:
                # Secondary check: same phone number or same core name + postal code
                existing = self._find_secondary_match(comp, unique_companies)

            if existing is not None:
                self._merge_company_records(existing, comp)
            else:
                comp.company_id = generate_company_id(comp.domain, comp.company_name)
                unique_companies.append(comp)
                if comp.domain:
                    by_domain[comp.domain] = comp
                if comp.normalized_name:
                    by_norm_name[comp.normalized_name] = comp

        return unique_companies

    def _find_secondary_match(
        self, candidate: Company, existing_list: List[Company]
    ) -> Optional[Company]:
        """Check if candidate matches an existing company by phone or core brand + PLZ."""
        cand_phone = normalize_phone(candidate.phone)
        cand_core = GENERIC_DESCRIPTORS_PATTERN.sub("", candidate.normalized_name).strip()

        for ex in existing_list:
            ex_phone = normalize_phone(ex.phone)
            if cand_phone and ex_phone and cand_phone == ex_phone:
                return ex

            ex_core = GENERIC_DESCRIPTORS_PATTERN.sub("", ex.normalized_name).strip()
            if (
                cand_core
                and len(cand_core) >= 5
                and cand_core == ex_core
                and candidate.postal_code
                and candidate.postal_code == ex.postal_code
            ):
                return ex
        return None

    def _merge_company_records(self, target: Company, source: Company) -> Company:
        """Merge non-null attributes and list fields from source into target."""
        # Prefer shorter/cleaner official name if target name looks like a raw page title
        if len(source.company_name) < len(target.company_name) and len(source.company_name) >= 4:
            if "|" in target.company_name or "-" in target.company_name:
                target.company_name = source.company_name

        scalar_fields = [
            "website",
            "domain",
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
            "metering_relevance",
            "company_size",
            "employee_count",
            "berlin_presence",
            "cooperation_notes",
        ]
        for field in scalar_fields:
            if getattr(target, field) is None and getattr(source, field) is not None:
                setattr(target, field, getattr(source, field))

        list_fields = [
            "property_types",
            "services",
            "metering_signals",
            "geographic_coverage",
            "growth_signals",
            "source_urls",
        ]
        for field in list_fields:
            target_list: List[str] = getattr(target, field)
            source_list: List[str] = getattr(source, field)
            seen = {item.lower().strip() for item in target_list}
            for item in source_list:
                if item and item.lower().strip() not in seen:
                    target_list.append(item)
                    seen.add(item.lower().strip())

        return target

    def verify_evidence_against_text(
        self, evidence: Evidence, page_texts_by_url: Dict[str, str]
    ) -> VerificationStatus:
        """Verify whether an Evidence supporting quote actually appears in the scraped text."""
        if not evidence.supporting_text or len(evidence.supporting_text.strip()) < 3:
            evidence.verification_status = VerificationStatus.REJECTED_NO_EVIDENCE
            return evidence.verification_status

        # Normalize whitespace for comparison
        quote_norm = re.sub(r"\s+", " ", evidence.supporting_text.lower()).strip()
        all_text = " ".join(page_texts_by_url.values()).lower()
        all_text_norm = re.sub(r"\s+", " ", all_text)

        if quote_norm in all_text_norm:
            evidence.verification_status = VerificationStatus.VERIFIED_TEXT_MATCH
            return evidence.verification_status

        # Check token overlap or numeric presence if LLM slightly condensed whitespace/formatting
        quote_tokens = [t for t in re.findall(r"\w+", quote_norm) if len(t) > 2]
        if quote_tokens:
            matched_tokens = sum(1 for t in quote_tokens if t in all_text_norm)
            overlap_ratio = matched_tokens / len(quote_tokens)
            # For numerical fields, the exact number (with or without thousand separator) must exist in text
            numbers_in_value = re.findall(r"\d+", str(evidence.extracted_value))
            numbers_present = all(
                (num in all_text_norm or f"{int(num):,}".replace(",", ".") in all_text_norm)
                for num in numbers_in_value
            )
            if overlap_ratio >= 0.75 and numbers_present:
                evidence.verification_status = VerificationStatus.VERIFIED_TEXT_MATCH
                return evidence.verification_status

        evidence.verification_status = VerificationStatus.UNVERIFIED
        return evidence.verification_status

    def enforce_company_evidence_consistency(
        self, company: Company, evidences: List[Evidence]
    ) -> Tuple[Company, List[Evidence]]:
        """Nullify quantitative fields on a Company if they lack valid supporting Evidence.

        This guarantees the system never retains hallucinated building, unit, or employee counts.
        """
        valid_evidences = [
            e
            for e in evidences
            if e.company_id == company.company_id
            and e.verification_status != VerificationStatus.REJECTED_NO_EVIDENCE
            and len(e.supporting_text.strip()) >= 3
        ]
        ev_by_field: Dict[str, List[Evidence]] = {}
        for ev in valid_evidences:
            ev_by_field.setdefault(ev.field_name, []).append(ev)

        strict_numeric_fields = [
            "managed_buildings",
            "managed_residential_units",
            "managed_commercial_units",
            "managed_total_units",
            "employee_count",
        ]
        for num_field in strict_numeric_fields:
            val = getattr(company, num_field)
            if val is not None:
                field_evs = ev_by_field.get(num_field, [])
                if not field_evs:
                    logger.warning(
                        "Stripping unsupported quantitative field %s=%s for company %s (no evidence)",
                        num_field,
                        val,
                        company.company_name,
                    )
                    setattr(company, num_field, None)
                else:
                    # Verify that the number or German formatted number appears in the supporting quote
                    val_str = str(val)
                    val_de = f"{val:,}".replace(",", ".")
                    has_num_in_quote = any(
                        (val_str in ev.supporting_text or val_de in ev.supporting_text)
                        for ev in field_evs
                    )
                    if not has_num_in_quote:
                        logger.warning(
                            "Stripping quantitative field %s=%s for company %s (number not present in quote)",
                            num_field,
                            val,
                            company.company_name,
                        )
                        setattr(company, num_field, None)

        return company, valid_evidences
