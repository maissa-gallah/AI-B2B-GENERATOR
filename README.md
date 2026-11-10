# Heidi Systems — AI-Powered B2B Lead Generation System

An end-to-end, compliance-first B2B lead discovery, multi-page website extraction, DeepSeek AI information extraction, deterministic KPI qualification, and decision-maker contact research pipeline tailored for **Heidi Systems GmbH**.

---

## 1. Project Purpose & Business Context

**Heidi Systems GmbH** (based at Monbijouplatz, Berlin) is a digital submetering service provider (*digitaler Messdienstleister*) and PropTech platform offering:
* Radio-based open-standard (OMS) heat cost allocators (*Funk-Heizkostenverteiler*), hot/cold water meters, and smart smoke detectors (*Funk-Rauchwarnmelder*).
* Seamless mid-contract takeover of existing open-standard meters (*Bestandszähler-Übernahme*) from legacy providers (Techem, Ista, Brunata, Kalorimeta).
* Automated heating and utility billing (*Heiz- und Betriebskostenabrechnung*) compliant with *HKVO* and *MessEG*, plus mandatory monthly consumption updates (*uVI*).
* Direct API/ERP interfaces (*Schnittstellen*) and digital portals for property managers.

**Objective:** Discover property management companies (*Hausverwaltungen*) operating in Berlin, extract verifiable portfolio and service intelligence from their official websites, qualify them using an explainable deterministic KPI scoring engine (0–100), identify publicly listed decision-makers (*Geschäftsführer*, *Technischer Leiter*, *Head of Property Management*), and generate a professionally formatted 5-sheet Excel workbook.

---

## 2. System Architecture

The system follows a modular, deterministic pipeline architecture where **DeepSeek (`deepseek-chat`) via LangChain** is strictly responsible for structured text extraction with mandatory verbatim evidence quotes, while **Python** deterministically handles deduplication, anti-hallucination verification, DNS MX email checks, KPI math, and Excel generation.

```text
AI-B2B-GENERATOR/
├── pyproject.toml                  # uv project metadata, dependencies, pytest config
├── uv.lock                         # Deterministic dependency lockfile
├── .env.example                    # Environment configuration template
├── Dockerfile                      # Reproducible container build with uv
├── docker-compose.yml              # Application + optional MongoDB 7.0 service
├── README.md                       # Complete setup and usage documentation
├── docs/
│   └── methodology_report.md       # Detailed business & technical methodology report
├── config/
│   └── kpi_weights.yaml            # Configurable KPI weights, thresholds & German queries
├── src/
│   ├── config.py                   # Pydantic Settings & YAML configuration loader
│   ├── main.py                     # CLI pipeline orchestrator (--stage all|discover|enrich|qualify|export)
│   ├── api.py                      # FastAPI REST application
│   ├── models/                     # Pydantic v2 models (Company, Evidence, Contact, LeadQualification)
│   ├── prompts/                    # Versioned LangChain prompts for DeepSeek structured extraction
│   ├── services/
│   │   ├── discovery.py            # 1. Discovery Service (Tavily, Exa, Brave, Free Search/Directory)
│   │   ├── website_extractor.py    # 2. Website Extraction Service (Requests + BeautifulSoup4 + lxml)
│   │   ├── ai_extractor.py         # 3. AI Information Extraction Service (LangChain + DeepSeek)
│   │   ├── qualification.py        # 4. Lead Qualification Service (Deterministic Python KPI Engine)
│   │   ├── contact_research.py     # 5. Contact Research Service (Impressum/Team + DNS MX Verification)
│   │   ├── validation.py           # 6. Validation & Deduplication Service (Hallucination Guard)
│   │   └── exporter.py             # 7. Export Service (Pandas + OpenPyXL 5-Sheet Excel Generator)
│   └── storage/
│       └── repository.py           # JSON checkpoint persistence + optional MongoDB adapter
├── data/
│   ├── cache/                      # Local cache for search queries, HTML pages, and LLM responses
│   └── output/                     # JSON state checkpoints & final heidi_berlin_leads.xlsx
└── tests/                          # Comprehensive pytest suite (models, deduplication, KPIs, export)
```

---

## 3. Technology Stack & Justification

* **Python 3.12 & `uv`**: Ultra-fast, reproducible virtual environment and lockfile management.
* **LangChain (`langchain-core`, `langchain-openai`) + DeepSeek (`deepseek-chat`)**: Structured output extraction (`CompanyExtractionLLMOutput`, `ContactExtractionLLMOutput`) at `temperature=0.0` with automatic JSON fallback and disk caching.
* **Pydantic v2 & `pydantic-settings`**: Strict schema validation, nullability enforcement, and environment config management.
* **Multi-Provider Discovery (`requests`, `BeautifulSoup4`)**: Supports **Tavily API**, **Exa API**, **Brave Search API**, and **Keyless Free Search / Public Berlin Directory** out of the box.
* **Website Scraping (`requests`, `BeautifulSoup4`, `lxml`)**: Polite multi-page HTML crawler respecting `robots.txt` that targets `/impressum`, `/ueber-uns`, `/team`, `/leistungen`, `/referenzen`, and `/kontakt`.
* **Email & DNS Verification (`dnspython`)**: Performs live DNS `MX`/`A` record lookups on published email domains (`Technically deliverability-checked` vs. `Publicly published` vs. `Not found`).
* **Storage (`JSON` + `pymongo`)**: Zero-configuration local JSON persistence in `data/output/` for immediate runnability and crash recovery, with seamless MongoDB sync when `STORAGE_BACKEND=mongodb`.
* **Deliverable Export (`pandas` + `openpyxl`)**: Generates a styled, filterable 5-sheet Excel workbook with conditional priority highlighting, freeze panes, and auto-fitted columns.
* **REST API (`FastAPI` + `uvicorn`)**: Exposes endpoints to inspect leads, evidence, contacts, and download the Excel deliverable.

---

## 4. Installation & Environment Configuration

### Prerequisites
* Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) installed.

### 1. Install Dependencies with `uv`
```bash
uv sync --extra dev
```

### 2. Configure Environment Variables (`.env`)
Copy `.env.example` to `.env` and add your API key(s):
```bash
cp .env.example .env
```

Key environment variables in `.env`:
```ini
# LLM Provider (Default: DeepSeek)
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# Search Provider ("auto" automatically uses Tavily, Exa, Brave, or free discovery)
SEARCH_PROVIDER=auto
TAVILY_API_KEY=
EXA_API_KEY=
BRAVE_API_KEY=

# Storage ("json" or "mongodb")
STORAGE_BACKEND=json
```

---

## 5. Execution Instructions

### Run the Full Pipeline via CLI
```bash
uv run python -m src.main --stage all --max-companies 16 --output heidi_berlin_leads.xlsx
```

### Run Individual Pipeline Stages Incrementally
Because every stage checkpoints its state to `data/output/*.json` and caches HTTP/LLM responses in `data/cache/`, you can run or re-run individual stages at any time without repeating expensive API calls:

```bash
# Stage 1: Discover and deduplicate Berlin property management companies
uv run python -m src.main --stage discover --max-companies 20

# Stage 2, 3 & 5: Crawl websites, extract company info with DeepSeek, and research contacts
uv run python -m src.main --stage enrich

# Stage 4: Run deterministic KPI scoring and priority classification
uv run python -m src.main --stage qualify

# Stage 7: Generate the 5-sheet Excel workbook in data/output/heidi_berlin_leads.xlsx
uv run python -m src.main --stage export --output heidi_berlin_leads.xlsx
```

### Run the FastAPI Server
```bash
uv run uvicorn src.api:app --host 0.0.0.0 --port 8000
```
* Interactive Swagger UI: `http://localhost:8000/docs`
* Download Excel Deliverable: `GET http://localhost:8000/api/v1/export/excel`

### Run Unit Tests
```bash
uv run pytest
```

### Run with Docker Compose (App + MongoDB)
```bash
docker compose up --build
```

---

## 6. Validation Methodology & Quality Safeguards

1. **Zero Hallucinated Numbers (`ValidationService.enforce_company_evidence_consistency`):**
   Every quantitative field (`managed_buildings`, `managed_residential_units`, `managed_commercial_units`, `managed_total_units`, `employee_count`) is cross-checked against its `Evidence` quote. If no verbatim quote exists or the number does not appear in the quote, the field is automatically reset to `null`.
2. **Missing Data Neutrality (`LeadQualificationService`):**
   Missing quantitative fields are marked `is_known=False` and handled via a blended formula (`0.70 * Raw_Score + 0.30 * Known_Normalized_Score`) so established Berlin *Hausverwaltungen* that do not publish unit counts on their websites are not penalized as having 0 units.
3. **Strict Email Compliance (`ContactResearchService`):**
   Emails are never guessed from name patterns. Only emails physically present in the scraped HTML are retained, classified as Personal vs. Generic (`info@`), and checked against DNS `MX` records.
4. **Test Fixture Isolation:**
   Synthetic records used in `tests/` carry `is_sample_record=True` and are automatically excluded from production exports (`repository.list_companies(include_samples=False)`).

---

## 7. Known Limitations

* **JavaScript-Rendered Websites:** Websites that require client-side JS execution to render text may yield partial content via static HTTP requests; these are flagged in the `Crawl Status` column.
* **Self-Reported Website Figures:** Portfolio numbers (buildings, units, employees) reflect self-reported figures on company websites.
* **GDPR & Impressum Practices:** Many German property management companies list their managing directors (*Geschäftsführer*) by name in the `/impressum` alongside a central mailbox (`info@`) rather than personal email addresses.

For full details on the KPI weights and scoring formula, see [docs/methodology_report.md](file:///home/maissa/projects/personal_projects/AI-B2B-GENERATOR/docs/methodology_report.md).
