"""Storage repository supporting JSON persistence and optional MongoDB."""

from pathlib import Path
from typing import Dict, List, Optional
import json
import logging

from src.config import Settings
from src.models import Company, Contact, Evidence, LeadQualification

logger = logging.getLogger(__name__)


class LeadRepository:
    """Manages persistence of companies, evidence, contacts, and qualifications.

    Supports two backends:
    - 'json' (default): Stores structured JSON files in data/output/ for immediate portability.
    - 'mongodb': Persists documents in MongoDB collections while also maintaining JSON checkpoints.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_directories()
        self.output_dir: Path = self.settings.output_dir

        self.companies_path = self.output_dir / "companies.json"
        self.evidence_path = self.output_dir / "evidence.json"
        self.contacts_path = self.output_dir / "contacts.json"
        self.qualifications_path = self.output_dir / "qualifications.json"

        self._companies: Dict[str, Company] = {}
        self._evidence: Dict[str, Evidence] = {}
        self._contacts: Dict[str, Contact] = {}
        self._qualifications: Dict[str, LeadQualification] = {}

        self._mongo_db = None
        if self.settings.storage_backend.lower() == "mongodb":
            self._init_mongodb()

        self.load_from_disk()

    def _init_mongodb(self) -> None:
        """Initialize optional MongoDB connection if configured."""
        try:
            from pymongo import MongoClient

            client = MongoClient(self.settings.mongodb_uri, serverSelectionTimeoutMS=3000)
            client.admin.command("ping")
            self._mongo_db = client[self.settings.mongodb_database]
            logger.info("Connected to MongoDB database: %s", self.settings.mongodb_database)
        except Exception as exc:
            logger.warning(
                "MongoDB unavailable (%s). Falling back to local JSON persistence.", exc
            )
            self._mongo_db = None

    def load_from_disk(self) -> None:
        """Load existing records from local JSON checkpoint files if present."""
        if self.companies_path.exists():
            raw = json.loads(self.companies_path.read_text(encoding="utf-8"))
            self._companies = {item["company_id"]: Company.model_validate(item) for item in raw}

        if self.evidence_path.exists():
            raw = json.loads(self.evidence_path.read_text(encoding="utf-8"))
            self._evidence = {item["evidence_id"]: Evidence.model_validate(item) for item in raw}

        if self.contacts_path.exists():
            raw = json.loads(self.contacts_path.read_text(encoding="utf-8"))
            self._contacts = {item["contact_id"]: Contact.model_validate(item) for item in raw}

        if self.qualifications_path.exists():
            raw = json.loads(self.qualifications_path.read_text(encoding="utf-8"))
            self._qualifications = {
                item["company_id"]: LeadQualification.model_validate(item) for item in raw
            }

    def save_all(self) -> None:
        """Persist all current records to JSON checkpoint files (and MongoDB if enabled)."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.companies_path.write_text(
            json.dumps(
                [c.model_dump(mode="json") for c in self._companies.values()],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.evidence_path.write_text(
            json.dumps(
                [e.model_dump(mode="json") for e in self._evidence.values()],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.contacts_path.write_text(
            json.dumps(
                [c.model_dump(mode="json") for c in self._contacts.values()],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.qualifications_path.write_text(
            json.dumps(
                [q.model_dump(mode="json") for q in self._qualifications.values()],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        if self._mongo_db is not None:
            self._sync_to_mongodb()

    def _sync_to_mongodb(self) -> None:
        """Upsert records into MongoDB collections."""
        try:
            for c in self._companies.values():
                self._mongo_db.companies.update_one(
                    {"company_id": c.company_id},
                    {"$set": c.model_dump(mode="json")},
                    upsert=True,
                )
            for e in self._evidence.values():
                self._mongo_db.evidence.update_one(
                    {"evidence_id": e.evidence_id},
                    {"$set": e.model_dump(mode="json")},
                    upsert=True,
                )
            for ct in self._contacts.values():
                self._mongo_db.contacts.update_one(
                    {"contact_id": ct.contact_id},
                    {"$set": ct.model_dump(mode="json")},
                    upsert=True,
                )
            for q in self._qualifications.values():
                self._mongo_db.qualifications.update_one(
                    {"company_id": q.company_id},
                    {"$set": q.model_dump(mode="json")},
                    upsert=True,
                )
        except Exception as exc:
            logger.error("Error syncing to MongoDB: %s", exc)

    # --- CRUD Helpers ---

    def upsert_company(self, company: Company) -> None:
        self._companies[company.company_id] = company

    def get_company(self, company_id: str) -> Optional[Company]:
        return self._companies.get(company_id)

    def list_companies(self, include_samples: bool = False) -> List[Company]:
        companies = list(self._companies.values())
        if not include_samples:
            companies = [c for c in companies if not c.is_sample_record]
        return companies

    def add_evidence(self, evidence: Evidence) -> None:
        self._evidence[evidence.evidence_id] = evidence

    def get_company_evidence(self, company_id: str) -> List[Evidence]:
        return [e for e in self._evidence.values() if e.company_id == company_id]

    def list_evidence(self) -> List[Evidence]:
        return list(self._evidence.values())

    def add_contact(self, contact: Contact) -> None:
        self._contacts[contact.contact_id] = contact

    def get_company_contacts(self, company_id: str) -> List[Contact]:
        return [c for c in self._contacts.values() if c.company_id == company_id]

    def list_contacts(self) -> List[Contact]:
        return list(self._contacts.values())

    def upsert_qualification(self, qualification: LeadQualification) -> None:
        self._qualifications[qualification.company_id] = qualification

    def get_qualification(self, company_id: str) -> Optional[LeadQualification]:
        return self._qualifications.get(company_id)

    def list_qualifications(self) -> List[LeadQualification]:
        return list(self._qualifications.values())

    def clear_all(self) -> None:
        """Clear in-memory state (useful for isolated tests)."""
        self._companies.clear()
        self._evidence.clear()
        self._contacts.clear()
        self._qualifications.clear()
