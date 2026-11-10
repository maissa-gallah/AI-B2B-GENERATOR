# Heidi Systems — AI Agent Builder Case Study
**Automated B2B Lead Discovery, Qualification & Decision-Maker Research for Berlin Property Management Companies (*Hausverwaltungen*)**

---

## 1. Executive Summary & Results at a Glance

Instead of manually compiling a static list, I built an **end-to-end AI Agent & Deterministic Data Pipeline** specifically tailored to **Heidi Systems’** value proposition as a digital submetering service provider (*digitaler Messdienstleister*).

### Key Deliverable Metrics (`heidi_berlin_leads_100.xlsx`)
* **100 Unique Berlin Property Management Companies (*Hausverwaltungen*)** discovered, deduplicated, and enriched across Berlin (*PLZ 10xxx–14xxx*).
* **84 High-Priority Leads & 15 Medium-Priority Leads** scored using an explainable 8-KPI qualification engine (0–100 scale).
* **261 Verified Decision-Makers & Contacts** extracted:
  * **136 Tier-1 Executives** (*Geschäftsführer, Vorstand, Inhaber*)
  * **26 Tier-2 Technical & Operational Leads** (*Technischer Leiter, Prokurist, Teamleitung WEG/Mietverwaltung*)
  * **99 Tier-3 Property Managers** (*WEG-/Mietverwalter, Heizung/Sanitär/Technik*)
* **89 Direct Personal Email Addresses** (e.g., `m.domnig@abakus-immobilien.de`, `b.paul@abakus-immobilien.de`) explicitly separated from **161 Generic Company Mailboxes** (`info@`, `kontakt@`), with **250 emails technically deliverability-checked via live DNS `MX` record lookups**.
* **2,065 Verbatim Evidence Quotes** linking every extracted KPI, unit count, and contact person to its exact source URL on the company’s website.

---

## 2. Task 1: How I Discovered Berlin Property Management Companies

### Sources & Multi-Provider Discovery Engine
To maximize coverage of active Berlin *Hausverwaltungen* while avoiding dead directory entries, I built a multi-provider `DiscoveryService` supporting **Tavily Search API**, **Exa Search API**, **Brave Search API**, and **German Web Search / Verified Berlin Industry Directories**.

### Targeted German Search Query Matrix
We queried domain-specific German search combinations tailored to Heidi Systems’ core segments:
1. `Hausverwaltung Berlin WEG Mietverwaltung`
2. `Immobilienverwaltung Berlin GmbH`
3. `WEG-Verwaltung Berlin Wohneinheiten`
4. `Mietverwaltung Berlin Zinshausverwaltung`
5. `Gewerbeimmobilienverwaltung Berlin`
6. `Immobilienmanagement Berlin Hausverwaltung`
7. `Hausverwaltung Berlin Betriebskostenabrechnung`
8. `Hausverwaltung Berlin VDIV Mitglied`

### Automated Portal Filtering & Multi-Stage Deduplication
1. **Aggregator Exclusion:** Automatically filtered out 20+ non-target portals and directories (`immobilienscout24.de`, `immowelt.de`, `gelbeseiten.de`, `yelp.de`, `verwalter-vergleich.de`, `linkedin.com`, etc.) so only official company domains were retained.
2. **Deterministic Entity Resolution:** Deduplicated candidates across three layers:
   * Canonical root domain normalization.
   * Legal entity name normalization (stripping *GmbH*, *UG (haftungsbeschränkt)*, *GmbH & Co. KG*, *AG*, and standardizing German umlauts).
   * Cross-matching Berlin landline numbers (`+49 (0)30 ...` $\rightarrow$ `030...`) and 5-digit Berlin postal codes (`10xxx`–`14xxx`).

---

## 3. Task 2: Qualifying KPIs — Selection & Business Rationale

To determine whether a *Hausverwaltung* is a strong prospect for **Heidi Systems**, I analyzed Heidi Systems’ core offering:
* **Open-standard (OMS) radio submetering** (*Funk-Heizkostenverteiler, Wasserzähler, Wärmezähler, Funk-Rauchwarnmelder*).
* **Mid-contract takeover of existing hardware** (*Bestandszähler-Übernahme* from Techem, Ista, Brunata, Kalorimeta).
* **Automated HKVO & MessEG heating/utility billing** (*Heiz- und Betriebskostenabrechnung*) + monthly consumption updates (*uVI*).
* **ERP & Customer Portal integrations** (*Schnittstellen* to Casavi, Domus, Wodis, etc.).

### The 8 Qualifying KPIs (100-Point Scale)

| # | KPI Column in Sheet | Weight | Why It Matters for Heidi Systems | Scoring Logic |
| :- | :--- | :---: | :--- | :--- |
| **1** | **Property Types Managed** | **20 pts** | Multi-unit residential buildings require room-level heat/water submetering and annual *HKVO* billing. | **20 pts:** Both *WEG-Verwaltung* & *Mietverwaltung*<br>**16 pts:** Either *WEG* or *Mietverwaltung*<br>**12 pts:** *Gewerbe* or *SEV* only |
| **2** | **Metering & Billing Relevance** | **20 pts** | Companies actively advertising *Betriebs-/Heizkostenabrechnung*, technical management, and digital ERP portals (*Casavi, Domus*) experience the highest pain from legacy metering providers and benefit immediately from Heidi’s APIs. | **20 pts:** Heating/Utility billing + Digital Portal/ERP<br>**15 pts:** Billing or Technical Management<br>**10 pts:** General full-service management |
| **3** | **Berlin Presence** | **15 pts** | Local field operations, installation density, and proximity to Heidi Systems’ Berlin HQ. | **15 pts:** Verified Berlin HQ (`10xxx–14xxx`)<br>**10 pts:** Greater Berlin / Brandenburg coverage |
| **4** | **Managed Units (*Wohneinheiten*)** | **15 pts** | Submetering revenue scales directly with the number of metered apartments/commercial units. | **15 pts:** $\ge 2,000$ units \| **12 pts:** $500–1,999$<br>**9 pts:** $100–499$ \| **5 pts:** $10–99$ |
| **5** | **Managed Buildings (*Objekte*)** | **10 pts** | Indicates number of heating systems, gateways, and property mandates. | **10 pts:** $\ge 50$ buildings \| **8 pts:** $20–49$<br>**5 pts:** $5–19$ \| **2 pts:** $1–4$ |
| **6** | **Decision-Maker Accessibility** | **10 pts** | Outbound sales conversion depends on reaching the *Geschäftsführer* or *Technischer Leiter* directly rather than getting stuck at a generic gatekeeper inbox. | **10 pts:** Named Tier-1/2 leader + direct email/LinkedIn<br>**7 pts:** Named leader + verified company contact<br>**3 pts:** Generic contact only |
| **7** | **Company Size (*Mitarbeiter*)** | **5 pts** | Proxy for portfolio scale when unit counts are not publicly disclosed. | **5 pts:** $\ge 20$ staff \| **3 pts:** $5–19$ staff<br>**1 pt:** $1–4$ staff |
| **8** | **Growth & Digitalization Signals** | **5 pts** | Association memberships (*VDIV, BVI*), digital owner/tenant portals, and active hiring indicate professionalized operations open to modern PropTech. | **5 pts:** 2+ signals (*VDIV/BVI*, Portal, Hiring)<br>**3 pts:** 1 signal |

### Handling Unpublished Data Fairly (Blended Scoring Formula)
In Germany, many established mid-sized *Hausverwaltungen* do not publish exact unit or employee counts on their websites. Penalizing missing numbers as `0` would falsely downgrade strong Berlin leads.
* Each KPI tracks both `points_earned` and an `is_known` boolean flag, computing a **Data Completeness %** ($W_{\text{known}} / 100$).
* **Final Lead Score:**
  $$\text{Total Score} = 0.70 \times S_{\text{raw}} + 0.30 \times \left(\frac{S_{\text{raw}}}{W_{\text{known}}} \times 100\right)$$
* This rewards companies with proven large portfolios (e.g., *Fiechtner & Schauerte* at **100.0**, *Ralph Management GmbH* at **97.0**, *Promeda Hausverwaltung* at **96.5**) while still surfacing high-fit Berlin managers that keep unit numbers private.

---

## 4. Bonus Task: Finding Decision-Makers & Personal Emails

Under German telemedia law (**§ 5 DDG**), every commercial website must publish an **Impressum** naming its legally authorized representatives (*Vertretungsberechtigte Geschäftsführer*). In addition, many *Hausverwaltungen* publish `/team` or `/ansprechpartner` pages with direct staff contact details.

1. **Targeted Subpage Crawling:** For each company, our polite crawler automatically prioritizes `/impressum`, `/team`, `/ansprechpartner`, `/ueber-uns`, and `/kontakt`.
2. **Email De-Obfuscation:** Automatically reconstructs obfuscated German email patterns (`name(at)domain.de`, `[at]`, `mailto:` links) before passing text to the LLM.
3. **Role Tiering for Heidi Systems’ Sales Motion:**
   * **Tier 1 (136 contacts):** *Geschäftsführer, Vorstand, Inhaber* (Strategic & contract sign-off).
   * **Tier 2 (26 contacts):** *Prokurist, Technischer Leiter, Teamleitung* (Operational & technical champions).
   * **Tier 3 (99 contacts):** *Zertifizierte WEG-/Mietverwalter, Meister Heizung & Sanitär* (Day-to-day users of metering & billing portals).
4. **Zero-Guessing Policy:** Unlike tools that guess `firstname.lastname@domain.de` and cause high bounce rates, our pipeline **only records emails physically found on the website**, explicitly flags **Personal Emails (89)** vs. **Generic Mailboxes (161)**, and extracts **LinkedIn URLs** when linked.

---

## 5. Task 3: Technical Architecture, Tools & Data Validation

### End-to-End Automation Pipeline

```
[1. Multi-Query Discovery]  ──► Tavily / Exa / Brave / German Search (8 Berlin queries)
         │
         ▼
[2. Polite Web Crawler]     ──► Requests + BeautifulSoup4 + lxml (robots.txt compliant)
         │                      Crawls Homepage + /impressum, /team, /leistungen, /referenzen
         ▼
[3. AI Extraction Agent]    ──► LangChain + DeepSeek (temperature=0.0, Pydantic v2 schemas)
         │                      Extracts KPIs, contacts & mandatory verbatim evidence quotes
         ▼
[4. Validation & Guards]    ──► Python Hallucination Guard + DNS MX Email Verification (dnspython)
         │
         ▼
[5. Deterministic Scoring]  ──► 8-KPI Blended Scoring Engine + Sales Outreach Angle Generator
         │
         ▼
[6. Multi-Sheet Deliverable]──► Pandas + OpenPyXL -> 5-Sheet Styled Workbook
```

### How We Validated the Data (4-Layer Quality Assurance)

1. **Deterministic Anti-Hallucination Guard (`ValidationService`):**
   * The LLM (`deepseek-chat` at `temperature=0.0`) is instructed to return `null` for any metric not explicitly stated and must provide a verbatim `supporting_text` quote and `source_url` for every extracted fact.
   * **Post-LLM Python Verification:** Our Python validation layer checks every extracted integer (`managed_buildings`, `managed_residential_units`, `managed_total_units`, `employee_count`). If the number (e.g., `3500` or `3.500`) does not literally appear inside the verbatim quote from the website, Python automatically strips the hallucinated value back to `None`.
2. **Live DNS `MX` / `A` Record Email Verification (`dnspython`):**
   * Every extracted email domain is checked against live DNS mail exchange (`MX`) records. **250 out of 250 extracted emails** passed live domain deliverability verification (`Technically deliverability-checked`).
3. **Full Audit Trail (`Sources and Validation` Sheet):**
   * All **2,065 extracted facts** are logged in Sheet 4 of the workbook with their exact `Source URL`, `Source Type`, `Verification Status`, and verbatim German quote from the website.
4. **Automated Test Suite (`pytest`):**
   * Unit tests verify deduplication, German legal suffix normalization, anti-hallucination stripping, KPI math, and workbook structure.

---

## 6. Guide to the Deliverable Workbook (`heidi_berlin_leads_100.xlsx`)

The Excel / Google Sheet deliverable is organized into **5 structured tabs** for immediate use by Heidi Systems’ sales and rev-ops teams:

1. **`Companies` (100 rows):** Master overview sorted by Lead Score descending, including Company Name, Priority, Score, Website, Berlin Address/PLZ, Phone, Property Types, Buildings, Residential/Commercial/Total Units, Services, Metering Relevance, ERP/Growth Signals, and Crawl Status.
2. **`Lead Qualification` (100 rows):** Full transparency into every lead’s score — showing Total Score, Data Completeness %, per-KPI point breakdowns, Reasoning Summary, and a tailored **Recommended Sales Outreach Angle** (e.g., pitching OMS mid-contract takeover + ERP integration).
3. **`Contacts` (261 rows):** Decision-makers sorted by Company Lead Score and Role Priority Tier (Tier 1 $\rightarrow$ Tier 3), with Position, Email Address, Email Type (`Personal / Direct` vs. `Generic`), DNS Verification Status, LinkedIn URL, and verbatim source quote.
4. **`Sources and Validation` (2,065 rows):** Complete field-level audit log linking every extracted value to its exact subpage URL and supporting quote.
5. **`Methodology`:** Built-in reference guide documenting the KPI weights, scoring math, and verification definitions.
