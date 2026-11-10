"""Website Extraction Service for politely fetching and cleaning company website pages."""

from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
import re
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
import urllib3

from src.config import Settings
from src.models.enums import CrawlStatus, SourceType

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# High-value subpage URL/anchor patterns on German Hausverwaltung websites
SUBPAGE_KEYWORDS: Dict[str, Tuple[int, SourceType]] = {
    "impressum": (100, SourceType.IMPRESSUM),
    "kontakt": (90, SourceType.IMPRESSUM),
    "ueber-uns": (85, SourceType.TEAM_PAGE),
    "über-uns": (85, SourceType.TEAM_PAGE),
    "uber-uns": (85, SourceType.TEAM_PAGE),
    "unternehmen": (80, SourceType.TEAM_PAGE),
    "team": (80, SourceType.TEAM_PAGE),
    "ansprechpartner": (80, SourceType.TEAM_PAGE),
    "leistungen": (75, SourceType.SERVICES_PAGE),
    "service": (70, SourceType.SERVICES_PAGE),
    "verwaltung": (70, SourceType.SERVICES_PAGE),
    "weg": (65, SourceType.SERVICES_PAGE),
    "mietverwaltung": (65, SourceType.SERVICES_PAGE),
    "referenzen": (60, SourceType.SERVICES_PAGE),
    "objekte": (60, SourceType.SERVICES_PAGE),
}


@dataclass
class ExtractedPage:
    """Represents cleaned text and metadata from a single fetched webpage."""

    url: str
    title: str
    text: str
    source_type: SourceType
    status_code: int = 200


@dataclass
class WebsiteCrawlResult:
    """Aggregated crawl result across a company's homepage and key subpages."""

    base_url: str
    crawl_status: CrawlStatus
    limitations: Optional[str] = None
    pages: List[ExtractedPage] = field(default_factory=list)
    emails_found: List[str] = field(default_factory=list)
    phones_found: List[str] = field(default_factory=list)
    linkedin_urls_found: List[str] = field(default_factory=list)

    def combined_text_for_llm(self, max_chars: int = 18000) -> str:
        """Format all scraped pages with explicit [SOURCE_URL] headers for LLM extraction."""
        sections: List[str] = []
        total_len = 0
        for p in self.pages:
            chunk = (
                f"=== PAGE SOURCE_URL: {p.url} (Type: {p.source_type.value}) ===\n"
                f"PAGE TITLE: {p.title}\n"
                f"{p.text}\n"
            )
            if total_len + len(chunk) > max_chars:
                remaining = max(0, max_chars - total_len)
                if remaining > 300:
                    sections.append(chunk[:remaining] + "\n...[TRUNCATED]")
                break
            sections.append(chunk)
            total_len += len(chunk)
        return "\n".join(sections)

    def page_texts_by_url(self) -> Dict[str, str]:
        """Return mapping of page URL to cleaned text for evidence verification."""
        return {p.url: f"{p.title}\n{p.text}" for p in self.pages}


EMAIL_REGEX = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,10}\b"
)
LINKEDIN_REGEX = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|company)/[A-Za-z0-9_\-%/]+",
    re.IGNORECASE,
)


class WebsiteExtractorService:
    """Fetches and parses public company websites while respecting robots.txt and rate limits."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache_dir: Path = self.settings.cache_dir / "pages"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            }
        )

    def _cache_file(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"page_{digest}.json"

    def _is_allowed_by_robots(self, base_url: str, target_url: str) -> bool:
        """Check robots.txt politely; allow if robots.txt is missing or unreachable."""
        try:
            parsed = urlparse(base_url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            resp = self.session.get(robots_url, timeout=5)
            if resp.status_code != 200:
                return True
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp.can_fetch("*", target_url)
        except Exception:
            return True

    def _fetch_html(self, url: str) -> Tuple[Optional[str], int, Optional[str]]:
        """Fetch HTML with local caching and fallback to HTTP if HTTPS fails."""
        cache_path = self._cache_file(url)
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                return cached.get("html"), cached.get("status_code", 200), cached.get("final_url", url)
            except Exception:
                pass

        try:
            resp = self.session.get(
                url,
                timeout=self.settings.http_timeout_seconds,
                allow_redirects=True,
            )
            content_type = resp.headers.get("Content-Type", "").lower()
            if "pdf" in content_type or "image" in content_type:
                return None, resp.status_code, resp.url

            if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"

            html = resp.text
            if resp.status_code == 200 and html:
                cache_path.write_text(
                    json.dumps(
                        {"html": html, "status_code": resp.status_code, "final_url": resp.url},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            time.sleep(min(self.settings.request_delay_seconds, 0.5))
            return html, resp.status_code, resp.url
        except requests.exceptions.SSLError:
            try:
                resp = self.session.get(
                    url,
                    timeout=self.settings.http_timeout_seconds,
                    allow_redirects=True,
                    verify=False,
                )
                return resp.text, resp.status_code, resp.url
            except Exception as exc:
                return None, 0, str(exc)
        except Exception as exc:
            return None, 0, str(exc)

    def crawl_company_website(self, website_url: Optional[str]) -> WebsiteCrawlResult:
        """Crawl homepage and up to `max_subpages_per_company` high-value subpages."""
        if not website_url:
            return WebsiteCrawlResult(
                base_url="",
                crawl_status=CrawlStatus.NO_WEBSITE,
                limitations="No website URL available for company.",
            )

        if not self._is_allowed_by_robots(website_url, website_url):
            return WebsiteCrawlResult(
                base_url=website_url,
                crawl_status=CrawlStatus.ACCESS_RESTRICTED,
                limitations="Blocked by website robots.txt policy.",
            )

        home_html, status_code, final_url = self._fetch_html(website_url)
        if not home_html or status_code >= 400 or status_code == 0:
            return WebsiteCrawlResult(
                base_url=website_url,
                crawl_status=CrawlStatus.HTTP_ERROR,
                limitations=f"HTTP fetch failed (status={status_code}).",
            )

        actual_base = final_url if final_url and final_url.startswith("http") else website_url
        result = WebsiteCrawlResult(
            base_url=actual_base,
            crawl_status=CrawlStatus.SUCCESS,
        )

        # Parse homepage and discover internal links
        home_page, candidate_subpages, emails, phones, linkedins = self._parse_html_page(
            home_html, actual_base, SourceType.COMPANY_HOMEPAGE
        )
        result.pages.append(home_page)
        self._merge_unique(result.emails_found, emails)
        self._merge_unique(result.phones_found, phones)
        self._merge_unique(result.linkedin_urls_found, linkedins)

        # Sort candidate subpages by priority score descending
        sorted_subpages = sorted(candidate_subpages, key=lambda x: x[0], reverse=True)
        visited_urls = {actual_base.rstrip("/"), website_url.rstrip("/")}

        subpages_fetched = 0
        for _, sub_url, sub_type in sorted_subpages:
            if subpages_fetched >= self.settings.max_subpages_per_company:
                break
            norm_sub = sub_url.rstrip("/")
            if norm_sub in visited_urls:
                continue
            visited_urls.add(norm_sub)

            sub_html, sub_status, sub_final = self._fetch_html(sub_url)
            if sub_html and 200 <= sub_status < 400:
                sub_page, _, s_emails, s_phones, s_linkedins = self._parse_html_page(
                    sub_html, sub_final or sub_url, sub_type
                )
                if len(sub_page.text.strip()) > 40:
                    result.pages.append(sub_page)
                    self._merge_unique(result.emails_found, s_emails)
                    self._merge_unique(result.phones_found, s_phones)
                    self._merge_unique(result.linkedin_urls_found, s_linkedins)
                    subpages_fetched += 1

        total_text_len = sum(len(p.text) for p in result.pages)
        if total_text_len < 250:
            result.crawl_status = CrawlStatus.PARTIAL_JS_LIMITATION
            result.limitations = (
                "Website returned minimal static text (<250 chars); likely relies heavily on client-side JavaScript rendering."
            )

        return result

    def _parse_html_page(
        self, html: str, page_url: str, source_type: SourceType
    ) -> Tuple[ExtractedPage, List[Tuple[int, str, SourceType]], List[str], List[str], List[str]]:
        """Extract clean text, contact signals, and prioritized internal subpage links."""
        soup = BeautifulSoup(html, "lxml")

        title = soup.title.get_text(" ", strip=True) if soup.title else ""

        # Extract meta description as high-signal context
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if meta_tag and meta_tag.get("content"):
            meta_desc = str(meta_tag.get("content")).strip()

        # Collect mailto links, emails, and LinkedIn links before stripping tags
        emails: List[str] = []
        linkedins: List[str] = []
        subpages: List[Tuple[int, str, SourceType]] = []

        base_domain = urlparse(page_url).netloc.lower().lstrip("www.")

        for a_tag in soup.find_all("a", href=True):
            href = str(a_tag["href"]).strip()
            anchor_text = a_tag.get_text(" ", strip=True).lower()

            if href.lower().startswith("mailto:"):
                mail_addr = href[7:].split("?")[0].strip()
                if EMAIL_REGEX.match(mail_addr):
                    emails.append(mail_addr.lower())
                continue

            full_link = urljoin(page_url, href).split("#")[0].rstrip("/")
            if LINKEDIN_REGEX.match(full_link):
                linkedins.append(full_link)
                continue

            link_parsed = urlparse(full_link)
            link_domain = link_parsed.netloc.lower().lstrip("www.")
            if link_domain != base_domain:
                continue
            if any(
                full_link.lower().endswith(ext)
                for ext in (".pdf", ".jpg", ".png", ".zip", ".doc", ".xml", ".css", ".js")
            ):
                continue

            path_and_anchor = f"{link_parsed.path.lower()} {anchor_text}"
            for kw, (priority, stype) in SUBPAGE_KEYWORDS.items():
                if kw in path_and_anchor:
                    subpages.append((priority, full_link, stype))
                    break

        # Remove noisy script, style, and svg tags
        for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
            tag.decompose()

        raw_text = soup.get_text(separator="\n", strip=True)
        # De-obfuscate common German Impressum email patterns like "(at)" or "[at]"
        deobfuscated = re.sub(
            r"([A-Za-z0-9._%+-]+)\s*(?:\(at\)|\[at\]|\s+at\s+)\s*([A-Za-z0-9.-]+\.[A-Za-z]{2,10})",
            r"\1@\2",
            raw_text,
            flags=re.IGNORECASE,
        )

        for match in EMAIL_REGEX.findall(deobfuscated):
            lower_m = match.lower()
            if not any(
                lower_m.endswith(bad)
                for bad in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", "sentry.io", "example.com")
            ):
                emails.append(lower_m)

        phones = [
            m.strip()
            for m in re.findall(
                r"(?:\+49|0)[\s\-\(\)0]*30[\s\-\d\/]{5,14}", deobfuscated
            )
        ]

        # Clean lines and collapse excessive blank lines
        lines = [re.sub(r"\s+", " ", line).strip() for line in deobfuscated.splitlines()]
        clean_lines = [line for line in lines if len(line) >= 2]
        if meta_desc:
            clean_lines.insert(0, f"Meta Description: {meta_desc}")

        cleaned_text = "\n".join(clean_lines)

        page_obj = ExtractedPage(
            url=page_url,
            title=title,
            text=cleaned_text[:12000],
            source_type=source_type,
        )
        return page_obj, subpages, emails, phones, linkedins

    @staticmethod
    def _merge_unique(target: List[str], items: List[str]) -> None:
        seen = {x.lower() for x in target}
        for item in items:
            if item and item.lower() not in seen:
                target.append(item)
                seen.add(item.lower())
