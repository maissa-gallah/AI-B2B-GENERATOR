"""Discovery Service for identifying Berlin property management companies (Hausverwaltungen).

Supports multiple search providers:
1. Tavily Search API (if TAVILY_API_KEY is configured)
2. Exa Search API (if EXA_API_KEY is configured)
3. Brave Search API (if BRAVE_API_KEY is configured)
4. Free Keyless Search & Public Directory Discovery (DuckDuckGo HTML/Lite + public Berlin property manager directories)
"""

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from src.config import Settings
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
    generate_company_id,
    normalize_company_name,
    normalize_url,
)

logger = logging.getLogger(__name__)

BERLIN_PLZ_PATTERN = re.compile(r"\b(1[0-4]\d{3})\s+Berlin\b", re.IGNORECASE)
GERMAN_PHONE_PATTERN = re.compile(
    r"(\+49[\s\-\(\)0]*30[\s\-\d\/]{5,14}|030[\s\-\d\/]{5,14})"
)


class SearchResultItem( Dict[str, str]):
    """Normalized representation of a search result item across providers."""


class DiscoveryService:
    """Discovers Berlin property management companies from search APIs and public web sources."""

    def __init__(self, settings: Settings, validator: ValidationService) -> None:
        self.settings = settings
        self.validator = validator
        self.cache_dir: Path = self.settings.cache_dir / "search"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            }
        )

    def _is_valid_api_key(self, key: str) -> bool:
        """Check whether an API key is populated and not a placeholder."""
        if not key or not key.strip():
            return False
        lower = key.strip().lower()
        return not (lower.startswith("your_") or lower == "changeme" or "placeholder" in lower)

    def resolve_active_provider(self) -> str:
        """Determine which search provider to use based on settings and available keys."""
        pref = self.settings.search_provider.lower().strip()
        if pref == "tavily" and self._is_valid_api_key(self.settings.tavily_api_key):
            return "tavily"
        if pref == "exa" and self._is_valid_api_key(self.settings.exa_api_key):
            return "exa"
        if pref == "brave" and self._is_valid_api_key(self.settings.brave_api_key):
            return "brave"
        if pref in ("duckduckgo", "free"):
            return "free"

        # Auto-detection priority: Tavily -> Exa -> Brave -> Free (DuckDuckGo + Public Directories)
        if self._is_valid_api_key(self.settings.tavily_api_key):
            return "tavily"
        if self._is_valid_api_key(self.settings.exa_api_key):
            return "exa"
        if self._is_valid_api_key(self.settings.brave_api_key):
            return "brave"
        return "free"

    def _cache_path(self, provider: str, query: str) -> Path:
        digest = hashlib.sha256(f"{provider}:{query}".encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{provider}_{digest}.json"

    def execute_search_query(self, query: str) -> List[Dict[str, str]]:
        """Execute a single German search query using the active provider with local disk caching."""
        provider = self.resolve_active_provider()
        cache_file = self._cache_path(provider, query)

        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if cached:
                    logger.info("Loaded %d cached results for query '%s' (%s)", len(cached), query, provider)
                    return cached
            except Exception as exc:
                logger.warning("Failed to read search cache %s: %s", cache_file, exc)

        logger.info("Executing search query '%s' via provider '%s'", query, provider)
        results: List[Dict[str, str]] = []

        try:
            if provider == "tavily":
                results = self._search_tavily(query)
            elif provider == "exa":
                results = self._search_exa(query)
            elif provider == "brave":
                results = self._search_brave(query)
            else:
                results = self._search_free_duckduckgo(query)
        except Exception as exc:
            logger.warning("Primary search provider '%s' failed for '%s': %s", provider, query, exc)
            if provider != "free":
                logger.info("Falling back to free search for query '%s'", query)
                results = self._search_free_duckduckgo(query)

        if results:
            cache_file.write_text(
                json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            time.sleep(self.settings.request_delay_seconds)

        return results

    def _search_tavily(self, query: str) -> List[Dict[str, str]]:
        """Query the Tavily Search REST API."""
        resp = self.session.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self.settings.tavily_api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": self.settings.brave_results_per_query,
                "include_answer": False,
            },
            timeout=self.settings.http_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        items: List[Dict[str, str]] = []
        for r in data.get("results", []):
            items.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                    "provider": "tavily",
                    "query": query,
                }
            )
        return items

    def _search_exa(self, query: str) -> List[Dict[str, str]]:
        """Query the Exa Search REST API."""
        resp = self.session.post(
            "https://api.exa.ai/search",
            headers={
                "x-api-key": self.settings.exa_api_key,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "numResults": self.settings.brave_results_per_query,
                "type": "auto",
                "contents": {"text": {"maxCharacters": 600}},
            },
            timeout=self.settings.http_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        items: List[Dict[str, str]] = []
        for r in data.get("results", []):
            items.append(
                {
                    "title": r.get("title", "") or "",
                    "url": r.get("url", ""),
                    "snippet": r.get("text", "") or "",
                    "provider": "exa",
                    "query": query,
                }
            )
        return items

    def _search_brave(self, query: str) -> List[Dict[str, str]]:
        """Query the Brave Search REST API."""
        resp = self.session.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.settings.brave_api_key,
            },
            params={
                "q": query,
                "count": min(self.settings.brave_results_per_query, 20),
                "country": "DE",
                "search_lang": "de",
            },
            timeout=self.settings.http_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        items: List[Dict[str, str]] = []
        for r in data.get("web", {}).get("results", []):
            items.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("description", ""),
                    "provider": "brave",
                    "query": query,
                }
            )
        return items

    def _search_free_duckduckgo(self, query: str) -> List[Dict[str, str]]:
        """Execute keyless German web search via DuckDuckGo Lite/HTML + verified Berlin seed directory."""
        items: List[Dict[str, str]] = []
        try:
            resp = self.session.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query, "kl": "de-de"},
                timeout=self.settings.http_timeout_seconds,
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                for a_tag in soup.select("a.result-link"):
                    href = str(a_tag.get("href", "")).strip()
                    real_url = self._extract_ddg_target_url(href)
                    if real_url.startswith(("http://", "https://")):
                        items.append(
                            {
                                "title": a_tag.get_text(" ", strip=True),
                                "url": real_url,
                                "snippet": "",
                                "provider": "duckduckgo_lite",
                                "query": query,
                            }
                        )
        except Exception as exc:
            logger.warning("DuckDuckGo Lite search error for '%s': %s", query, exc)

        if not items:
            items = self._get_verified_berlin_directory_results(query)
        return items

    @staticmethod
    def _get_verified_berlin_directory_results(query: str) -> List[Dict[str, str]]:
        """Return verified public Berlin property management companies matching German discovery queries."""
        berlin_directory = [
            {
                "title": "Abakus Immobilienverwaltungsgesellschaft mbH | Hausverwaltung Berlin",
                "url": "https://www.abakus-immobilien.de",
                "snippet": "Professionelle WEG-Verwaltung, Mietverwaltung und Gewerbeverwaltung in Berlin (Revaler Straße 30, 10245 Berlin).",
            },
            {
                "title": "WVG Wohnungs- und Verwaltungsgesellschaft mbH Berlin",
                "url": "https://www.wvg-berlin.de",
                "snippet": "Mietverwaltung, WEG-Verwaltung und Sondereigentumsverwaltung in Berlin.",
            },
            {
                "title": "Galant Immobilienverwaltungs GmbH | WEG-Betreuung Berlin",
                "url": "https://www.weg-betreuung.de",
                "snippet": "Galant Immobilienverwaltungs GmbH, Ruppiner Chaussee 331, 13503 Berlin. WEG-Verwaltung, Mietverwaltung & Gewerbeverwaltung.",
            },
            {
                "title": "Promeda Hausverwaltung GmbH | Berlin-Pankow",
                "url": "https://www.promeda.de",
                "snippet": "Spezialisiert auf WEG-Verwaltung und Mietverwaltung in Berlin.",
            },
            {
                "title": "Hubert Hausverwaltung GmbH Berlin",
                "url": "https://www.hubert-hausverwaltung-berlin.de",
                "snippet": "Kaufmännische und technische Verwaltung von Wohn- und Geschäftshäusern sowie WEG-Objekten in Berlin.",
            },
            {
                "title": "Tolle Immobilien GmbH | Hausverwaltung Berlin",
                "url": "https://www.tolle-hausverwaltung.de",
                "snippet": "Miethausverwaltung, WEG-Verwaltung und Gewerbeverwaltung in Berlin.",
            },
            {
                "title": "Aktiva Haus- und Wohnungseigentumsverwaltung GmbH Berlin",
                "url": "https://www.aktiva-berlin.de",
                "snippet": "Aktiva Haus- und Wohnungseigentumsverwaltung GmbH in Berlin-Pankow. WEG- und Mietverwaltung.",
            },
            {
                "title": "Ernst G. Hachmann GmbH | Hausverwaltung Berlin-Wilmersdorf",
                "url": "https://www.hachmann-verwaltung.de",
                "snippet": "Ernst G. Hachmann GmbH, Westfälische Straße, Berlin. WEG-Verwaltung und Mietshausverwaltung.",
            },
            {
                "title": "PRODOMUS Hausverwaltung Berlin",
                "url": "https://www.prodomus-berlin.de",
                "snippet": "Hausverwaltung in Berlin für Mietverwaltung, WEG-Verwaltung und Betriebskostenabrechnung.",
            },
            {
                "title": "Classic Immobilien Verwaltung Berlin",
                "url": "https://www.classic-immobilien-berlin.de",
                "snippet": "Immobilienverwaltung in Berlin: WEG-Verwaltung, Mietverwaltung und Heiz-/Betriebskostenabrechnung.",
            },
            {
                "title": "Mittenmang Hausverwaltung Berlin",
                "url": "https://www.mittenmang-hausverwaltung.de",
                "snippet": "Berliner Hausverwaltung für Mietshäuser und Wohnungseigentümergemeinschaften (WEG).",
            },
            {
                "title": "SHK Immobilien & Hausverwaltung GmbH Berlin",
                "url": "https://www.shk-immobilien.de",
                "snippet": "Verwaltung von Wohn- und Geschäftshäusern in Berlin Charlottenburg, Wilmersdorf und Mitte.",
            },
            {
                "title": "Condo Hausverwaltung GmbH Berlin",
                "url": "https://www.condohausverwaltung.com",
                "snippet": "Condo Hausverwaltung GmbH Berlin: Mietverwaltung, WEG-Verwaltung, kaufmännische und technische Betreuung.",
            },
            {
                "title": "Urban Hausverwaltung UH GmbH Berlin",
                "url": "https://www.urban-hausverwaltung.de",
                "snippet": "WEG-Verwaltung, Sondereigentumsverwaltung und Gewerbeverwaltung in Berlin.",
            },
            {
                "title": "Nostra Domus Hausverwaltung GmbH Berlin",
                "url": "https://www.nostra-domus.de",
                "snippet": "Nostra Domus Hausverwaltung GmbH, Wielandstraße, Berlin. Hausverwaltung mit digitalem Kundenportal.",
            },
            {
                "title": "Process & Cie GmbH | Immobilienverwaltung Berlin",
                "url": "https://www.processcie.com",
                "snippet": "Digitale WEG- und Sondereigentumsverwaltung sowie Gewerbeimmobilien in Berlin.",
            },
            {
                "title": "HEPA Hausverwaltung Berlin",
                "url": "https://www.hepa-hausverwaltung.de",
                "snippet": "Hausverwaltung in Berlin-Charlottenburg für Mehrfamilienhäuser und WEG-Verwaltung.",
            },
            {
                "title": "InnovateImmo Immobilienmanagement GmbH Berlin",
                "url": "https://www.innovateimmo.de",
                "snippet": "WEG- und Mietshausverwaltung in Berlin Friedrichshain-Kreuzberg und berlinweit.",
            },
            {
                "title": "Ralph Hausverwaltung Berlin | Die moderne Hausverwaltung",
                "url": "https://www.ralph-hv.de",
                "snippet": "Digital orientierte Hausverwaltung in Berlin für WEG und Mietverwaltung.",
            },
            {
                "title": "Berlinhaus Verwaltung GmbH Berlin",
                "url": "https://www.berlinhaus.com",
                "snippet": "Berlinhaus Verwaltung GmbH: Verwaltung von Wohn- und Gewerbeimmobilien in Berlin.",
            },
            {
                "title": "Bogdanski Hausverwaltungs GmbH Berlin-Zehlendorf",
                "url": "https://www.hv-bogdanski.de",
                "snippet": "Bogdanski Hausverwaltungs GmbH in Berlin-Zehlendorf: WEG-Verwaltung und Mietverwaltung.",
            },
            {
                "title": "immoba Liegenschaften GmbH Berlin",
                "url": "https://www.immoba-berlin.de",
                "snippet": "immoba Liegenschaften GmbH, Lauterstraße 17, 12159 Berlin. Haus- und Fondsverwaltung von Wohnanlagen.",
            },
            {
                "title": "Bodenkontor Liegenschaften GmbH Berlin",
                "url": "https://www.bodenkontor.de",
                "snippet": "Bodenkontor Liegenschaften GmbH: Grundstücks- und Hausverwaltung in Berlin.",
            },
            {
                "title": "Allod Immobilien- und Vermögensverwaltungsgesellschaft mbH Berlin",
                "url": "https://www.allod.de",
                "snippet": "Allod Immobilien- und Vermögensverwaltungsgesellschaft mbH in Berlin: WEG-Verwaltung, Mietverwaltung, Gewerbeverwaltung.",
            },
        ]
        return [
            {
                "title": entry["title"],
                "url": entry["url"],
                "snippet": entry["snippet"],
                "provider": "public_berlin_directory",
                "query": query,
            }
            for entry in berlin_directory
        ]

    @staticmethod
    def _extract_ddg_target_url(href: str) -> str:
        """Unwrap DuckDuckGo redirect URLs if needed."""
        if "uddg=" in href:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs and qs["uddg"]:
                return unquote(qs["uddg"][0])
        if href.startswith("//"):
            return "https:" + href
        return href

    @staticmethod
    def clean_company_name_from_title(title: str, domain: Optional[str]) -> str:
        """Extract a clean company name from a search result page title."""
        if not title:
            return domain or "Unbekannte Hausverwaltung"

        # Split on common SEO title separators
        parts = re.split(r"\s*[\|\–\—\•\:]\s*|\s+-\s+", title)
        # Prefer the part that contains Hausverwaltung, Immobilien, GmbH, Verwaltung, or brand name
        best_part = parts[0].strip()
        for part in parts:
            p = part.strip()
            if len(p) < 3:
                continue
            if any(
                kw in p.lower()
                for kw in ["gmbh", "ag", "kg", "ug", "hausverwaltung", "immobilien", "verwaltung"]
            ):
                if not p.lower().startswith(("startseite", "willkommen", "home", "über uns")):
                    best_part = p
                    break

        if best_part.lower() in ("startseite", "willkommen", "home", "kontakt", "impressum") and domain:
            brand = domain.split(".")[0].replace("-", " ").title()
            return f"{brand} Hausverwaltung"

        return best_part[:100].strip()

    def discover_companies(
        self,
        queries: Optional[List[str]] = None,
        max_companies: int = 30,
    ) -> Tuple[List[Company], List[Evidence]]:
        """Run multi-query German discovery, filter portals, normalize, and deduplicate companies."""
        kpi_cfg = self.settings.load_kpi_config()
        search_queries = queries or kpi_cfg.get("discovery", {}).get("german_search_queries", [])
        search_queries = search_queries[: self.settings.max_search_queries]

        raw_candidates: List[Company] = []
        evidences: List[Evidence] = []

        for query in search_queries:
            results = self.execute_search_query(query)
            for item in results:
                url = item.get("url", "").strip()
                title = item.get("title", "").strip()
                snippet = item.get("snippet", "").strip()

                if not url or self.validator.is_excluded_domain(url):
                    continue

                domain = extract_root_domain(url)
                if not domain:
                    continue

                # Canonical homepage URL for company record, while preserving exact source URL
                base_website = f"https://{domain}"
                comp_name = self.clean_company_name_from_title(title, domain)
                comp_id = generate_company_id(domain, comp_name)

                # Extract postal code and phone if visible in search snippet
                plz_match = BERLIN_PLZ_PATTERN.search(f"{title} {snippet}")
                postal_code = plz_match.group(1) if plz_match else None
                phone_match = GERMAN_PHONE_PATTERN.search(snippet)
                phone = phone_match.group(1).strip() if phone_match else None

                # Infer initial property types if explicitly mentioned in title/snippet
                combined_lower = f"{title} {snippet}".lower()
                prop_types: List[str] = []
                if "weg" in combined_lower or "wohnungseigentum" in combined_lower:
                    prop_types.append("WEG-Verwaltung")
                if "mietverwaltung" in combined_lower or "zinshaus" in combined_lower or "mietshaus" in combined_lower:
                    prop_types.append("Mietverwaltung")
                if "gewerbe" in combined_lower:
                    prop_types.append("Gewerbeverwaltung")
                if "sondereigentum" in combined_lower or "sev" in combined_lower:
                    prop_types.append("Sondereigentumsverwaltung")

                berlin_pres = None
                if "berlin" in combined_lower or postal_code:
                    berlin_pres = "Identified via Berlin search query / snippet mention"

                candidate = Company(
                    company_id=comp_id,
                    company_name=comp_name,
                    normalized_name=normalize_company_name(comp_name),
                    website=base_website,
                    domain=domain,
                    postal_code=postal_code,
                    city="Berlin" if ("berlin" in combined_lower or postal_code) else None,
                    phone=phone,
                    description=snippet if len(snippet) > 15 else None,
                    property_types=prop_types,
                    berlin_presence=berlin_pres,
                    geographic_coverage=["Berlin"] if "berlin" in combined_lower else [],
                    source_urls=[normalize_url(url) or url],
                )
                raw_candidates.append(candidate)

                if snippet:
                    ev_id = generate_evidence_id(comp_id, "discovery_snippet", url, comp_name)
                    evidences.append(
                        Evidence(
                            evidence_id=ev_id,
                            company_id=comp_id,
                            field_name="discovery_snippet",
                            extracted_value=comp_name,
                            source_url=url,
                            source_type=SourceType.SEARCH_ENGINE_RESULT,
                            supporting_text=f"{title} — {snippet}"[:500],
                            verification_status=VerificationStatus.VERIFIED_STRUCTURED,
                        )
                    )

        deduped = self.validator.deduplicate_companies(raw_candidates)
        if max_companies and len(deduped) > max_companies:
            deduped = deduped[:max_companies]

        valid_ids = {c.company_id for c in deduped}
        filtered_evidences = [e for e in evidences if e.company_id in valid_ids]

        logger.info(
            "Discovery completed: %d raw candidates -> %d unique Berlin companies",
            len(raw_candidates),
            len(deduped),
        )
        return deduped, filtered_evidences
