"""Enumerations for Lead Qualification, Contact Verification, and Evidence Tracking."""

from enum import Enum


class LeadPriority(str, Enum):
    """Qualification priority tiers for Heidi Systems sales prospecting."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INSUFFICIENT_INFORMATION = "Insufficient Information"


class EmailStatus(str, Enum):
    """Strict distinction of contact email verification status."""

    PUBLICLY_PUBLISHED = "Publicly published"
    TECHNICALLY_DELIVERABILITY_CHECKED = "Technically deliverability-checked"
    UNVERIFIED = "Unverified"
    NOT_FOUND = "Not found"


class VerificationStatus(str, Enum):
    """Traceability and verification status for extracted evidence claims."""

    VERIFIED_TEXT_MATCH = "Verified (Exact/Substring Quote Match)"
    VERIFIED_STRUCTURED = "Verified (Structured Source)"
    UNVERIFIED = "Unverified"
    REJECTED_NO_EVIDENCE = "Rejected (Unsupported Claim)"


class SourceType(str, Enum):
    """Origin type of an extracted piece of evidence."""

    COMPANY_HOMEPAGE = "Company Homepage"
    IMPRESSUM = "Impressum / Legal Notice"
    TEAM_PAGE = "Team / About Us Page"
    SERVICES_PAGE = "Services / References Page"
    SEARCH_ENGINE_RESULT = "Search Engine Result"
    PUBLIC_DIRECTORY = "Public Business Directory / Association"


class CrawlStatus(str, Enum):
    """Status of website content extraction."""

    PENDING = "Pending"
    SUCCESS = "Success"
    PARTIAL_JS_LIMITATION = "Partial (Heavy JS / Dynamic Rendering)"
    ACCESS_RESTRICTED = "Access Restricted / Robots Blocked"
    HTTP_ERROR = "HTTP / Connection Error"
    NO_WEBSITE = "No Website Available"
