# Methodology Report: AI-Powered B2B Lead Generation System for Heidi Systems

## 1. Executive Summary & Business Context

This report documents the business research, technical architecture, data extraction pipeline, deterministic KPI qualification model, and compliance safeguards implemented for **Heidi Systems GmbH**.

### Verified Offering of Heidi Systems GmbH
Based on official company disclosures (`heidisystems.com`), commercial registry records (Amtsgericht Charlottenburg, HRB 259535 B, headquartered at Monbijouplatz, Berlin), and industry association partnerships (*VDIV* and *DEUMESS*):
1. **Digital Submetering (*Funkbasierte Messtechnik*):** Installation, operation, and remote reading (*Fernablesung*) of open-standard (OMS) radio heat cost allocators (*Funk-Heizkostenverteiler*), hot/cold water meters (*Warm-/Kaltwasserzähler*), heat meters (*Wärmezähler*), and smart radio smoke detectors (*Funk-Rauchwarnmelder*).
2. **Seamless Mid-Contract Takeover (*Bestandszähler-Übernahme*):** Ability to take over and read existing open-standard meters installed by legacy providers (e.g., Ista, Techem, Brunata-Metrona, Kalorimeta) even while legacy hardware rental contracts are still running.
3. **Automated HKVO & MessEG Billing:** Digital generation of annual heating and utility statements (*Heiz- und Betriebskostenabrechnung*) plus mandatory monthly consumption information (*unterjährige Verbrauchsinformation — uVI*).
4. **ERP & Portal Connectivity:** Automated data exchange interfaces (*Schnittstellen*) with property management ERP/CRM systems and digital tenant/owner portals.

### Ideal Customer Profile (ICP)
* **Target Sector:** Property management companies (*Hausverwaltungen* / *Immobilienverwaltungen*) operating in **Berlin, Germany**.
* **High-Value Portfolio Segments:**
  * **WEG-Verwaltung** (Condominium / homeowner associations)
  * **Mietverwaltung / Zinshausverwaltung** (Multi-family residential rental buildings)
  * **Gewerbeimmobilienverwaltung** & **Sondereigentumsverwaltung (SEV)**

---

## 2. Discovery Strategy (Task 1)

### Multi-Provider Search Architecture
The `DiscoveryService` (`src/services/discovery.py`) supports configurable search providers (`SEARCH_PROVIDER=auto|tavily|exa|brave|free`):
* **Tavily Search API** (`TAVILY_API_KEY`)
* **Exa Search API** (`EXA_API_KEY`)
* **Brave Search API** (`BRAVE_API_KEY`)
* **Keyless German Search & Verified Public Berlin Directory** (DuckDuckGo Lite/HTML + verified public Berlin *Hausverwaltungen* directory)

### German Search Query Matrix
1. `Hausverwaltung Berlin WEG Mietverwaltung`
2. `Immobilienverwaltung Berlin GmbH`
3. `WEG-Verwaltung Berlin Wohneinheiten`
4. `Mietverwaltung Berlin Zinshausverwaltung`
5. `Gewerbeimmobilienverwaltung Berlin`
6. `Immobilienmanagement Berlin Hausverwaltung`
7. `Hausverwaltung Berlin Betriebskostenabrechnung`
8. `Hausverwaltung Berlin VDIV Mitglied`

### Deduplication & Portal Filtering
Aggregators and directories (`immobilienscout24.de`, `immowelt.de`, `gelbeseiten.de`, `yelp.de`, `linkedin.com`, `heidisystems.com`, etc.) are automatically filtered out. Candidate records are deterministically deduplicated by:
1. Normalized root domain (`extract_root_domain`).
2. Normalized legal name (`normalize_company_name`, stripping `GmbH`, `UG (haftungsbeschränkt)`, `GmbH & Co. KG`, `AG`, etc. and standardizing German umlauts).
3. Secondary matching on normalized Berlin phone numbers (`+49 (0)30 ...` $\rightarrow$ `030...`) or core brand name + 5-digit postal code (`PLZ`).

---

## 3. Website Extraction & DeepSeek AI Processing (Task 2)

### Polite Multi-Page Crawler
For each unique company, `WebsiteExtractorService` (`src/services/website_extractor.py`):
* Checks `robots.txt` compliance before crawling.
* Fetches the homepage and discovers internal links to high-value subpages prioritized by German domain keywords:
  * `/impressum` & `/kontakt` (Priority 90–100: Legal entity name, address, postal code, managing directors, phone, email)
  * `/ueber-uns`, `/unternehmen`, `/team`, `/ansprechpartner` (Priority 80–85: Employee count, company history, team contacts, VDIV/BVI memberships)
  * `/leistungen`, `/verwaltung`, `/weg`, `/mietverwaltung`, `/referenzen`, `/objekte` (Priority 60–75: Managed buildings, residential/commercial units, billing and ERP signals)
* De-obfuscates common German Impressum email formatting (`(at)` / `[at]`) and extracts `mailto:` links and LinkedIn URLs before cleaning HTML with `BeautifulSoup4` + `lxml`.

### Structured LLM Extraction & Anti-Hallucination Guard
`AIExtractorService` (`src/services/ai_extractor.py`) integrates **LangChain** (`langchain-core`, `langchain-openai`) with **DeepSeek** (`deepseek-chat` at `temperature=0.0`).
* Every quantitative metric (`managed_buildings`, `managed_residential_units`, `managed_commercial_units`, `managed_total_units`, `employee_count`) defaults to `null` (`None`).
* The LLM must return an `evidence_items` list linking each extracted fact to its exact `source_url` and a verbatim `supporting_text` quote.
* **Deterministic Hallucination Guard (`ValidationService.enforce_company_evidence_consistency`):** Even after LLM extraction, Python inspects every non-null number on a `Company` record. If no `Evidence` record exists for that field—or if the extracted integer (e.g. `1500` or `1.500`) does not literally appear in the `supporting_text` quote—Python strips the number back to `None`.

---

## 4. Deterministic KPI Qualification Methodology (Task 3)

### Why Missing Information Must Not Be Penalized
In the German property management industry, many established mid-sized *Hausverwaltungen* publish their full service catalog (*WEG-Verwaltung*, *Mietverwaltung*, *Betriebskostenabrechnung*), Berlin address, and *Impressum* managing directors (`Geschäftsführer`), but **do not publish exact unit or building counts** on their public websites.

If missing portfolio counts were scored as `0/15` and `0/10`, strong Berlin property managers would be artificially penalized by 25–30 points compared to their actual suitability.

### Blended Evidence-Weighted Formula
Every KPI is evaluated deterministically in Python (`LeadQualificationService` in `src/services/qualification.py`):
* Let $W_{\text{total}} = 100$ be the sum of all 8 KPI maximum weights.
* Let $W_{\text{known}}$ be the sum of maximum weights for KPIs where `is_known == True`.
* Let $S_{\text{raw}}$ be the sum of verified points earned across known KPIs.
* **Data Completeness (%):**
  $$\text{Completeness} = \frac{W_{\text{known}}}{W_{\text{total}}} \times 100$$
* **Known-Normalized Score:**
  $$S_{\text{norm}} = \frac{S_{\text{raw}}}{W_{\text{known}}} \times 100$$
* **Final Deterministic Lead Score (0–100):**
  $$\text{Total Score} = \text{round}\left(0.70 \times S_{\text{raw}} + 0.30 \times S_{\text{norm}}, 1\right)$$

### KPI Weighting & Rules Summary

| KPI | Max Points | Scoring Criteria | Missing Data Handling |
| :--- | :---: | :--- | :--- |
| **1. Berlin Presence** | **15** | 15 pts: Verified Berlin HQ (PLZ `10xxx`–`14xxx` or City=Berlin); 10 pts: Greater Berlin/Brandenburg coverage; 0 pts: Outside target region. | `is_known=False` if location cannot be determined. |
| **2. Property Types** | **20** | 20 pts: Both `WEG-Verwaltung` & `Mietverwaltung`; 16 pts: Either `WEG` or `Mietverwaltung`; 12 pts: `Gewerbe` or `SEV` only; 0 pts: Non-management. | `is_known=False` if no service pages available. |
| **3. Metering & Billing Relevance** | **20** | 20 pts: Utility/heating billing (*Heiz-/Betriebskostenabrechnung*) + digital portal/ERP (*Casavi*, *Domus*, *Kundenportal*); 15 pts: Billing or Technical Mgmt; 10 pts: General PM. | `is_known=False` if no service text available. |
| **4. Managed Units** | **15** | $\ge 2,000$: 15 pts; $500–1,999$: 12 pts; $100–499$: 9 pts; $10–99$: 5 pts; $1–9$: 2 pts. | `is_known=False` (neutral via blended normalization). |
| **5. Managed Buildings** | **10** | $\ge 50$: 10 pts; $20–49$: 8 pts; $5–19$: 5 pts; $1–4$: 2 pts. | `is_known=False` (neutral via blended normalization). |
| **6. Decision-Makers** | **10** | 10 pts: Named Tier-1/2 leader (*Geschäftsführer* / *Tech. Leiter*) + direct email/LinkedIn; 7 pts: Named leader + company contact; 3 pts: Generic contact only. | Evaluated deterministically from extracted `Contact` list. |
| **7. Company Size** | **5** | $\ge 20$ employees: 5 pts; $5–19$ employees: 3 pts; $1–4$ employees: 1 pt. | `is_known=False` (neutral via blended normalization). |
| **8. Growth Signals** | **5** | 5 pts: 2+ signals (VDIV/BVI membership, digital customer portal, active job openings); 3 pts: 1 signal; 0 pts: None. | `is_known=False` if website has minimal text. |

### Priority Classification Rules
* **High Priority:** `total_score >= 70.0` AND `data_completeness >= 50.0%` AND active in Berlin with relevant property management types.
* **Medium Priority:** `total_score >= 45.0` AND active in Berlin.
* **Low Priority:** `total_score < 45.0` with sufficient data (`data_completeness >= 35.0%`).
* **Insufficient Information:** `data_completeness < 35.0%` OR neither Berlin presence nor property types could be established.

---

## 5. Contact Research & Verification Compliance (Task 4)

Under German telemedia law (*§ 5 DDG*, formerly *TMG*), every GmbH or commercial website must publish an **Impressum** naming its legally authorized representatives (*Vertretungsberechtigte Geschäftsführer* / *Inhaber*).

`ContactResearchService` (`src/services/contact_research.py`):
1. Combines DeepSeek structured extraction (`ContactExtractionLLMOutput`) with a deterministic regex parser for German *Impressum* blocks.
2. Classifies roles into **Tier 1** (*Geschäftsführer / Managing Director / Vorstand / Inhaber*), **Tier 2** (*Technischer Leiter / Head of Property Management / Prokurist / Operations Manager*), and **Tier 3** (Other).
3. **Never invents or guesses email formats:** An email address is accepted *only* if it literally appeared in the scraped HTML (`crawl.emails_found`).
4. **Distinguishes Personal vs. Generic Mailboxes:** Clearly flags whether a published email is a personal address or a generic company mailbox (`info@`, `kontakt@`, `verwaltung@`).
5. **Technical Deliverability Check (`dnspython`):** Queries live DNS `MX` (and fallback `A`) records for every published email domain. Emails with verified mail exchangers are marked **`Technically deliverability-checked`**; otherwise **`Publicly published`**, **`Unverified`**, or **`Not found`**.

---

## 6. Known Limitations

1. **Client-Side JavaScript SPAs:** Websites built entirely as client-side JavaScript bundles without server-side HTML rendering yield limited text via `requests` + `BeautifulSoup`. These are transparently flagged with `Partial (Heavy JS / Dynamic Rendering)` or `HTTP / Connection Error` in the Excel output.
2. **Unpublished Portfolio Figures:** Because German *Hausverwaltungen* are privately held SMEs, many do not publish exact unit or employee counts on their websites. Our `data_completeness` metric and blended scoring formula explicitly surface this distinction.
3. **GDPR Email Practices:** To prevent spam, many Berlin *Hausverwaltungen* publish personal names of their *Geschäftsführer* in the *Impressum* alongside a central `info@` or `kontakt@` email rather than individual `vorname.nachname@` addresses. Our system preserves the named decision-maker and explicitly labels the email type rather than guessing personal emails.
