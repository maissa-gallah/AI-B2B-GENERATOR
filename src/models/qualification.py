"""LeadQualification data model for deterministic KPI scoring and explainability."""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from src.models.enums import LeadPriority


class KPIScoreBreakdown(BaseModel):
    """Detailed breakdown of a single KPI evaluation."""

    kpi_name: str = Field(..., description="Identifier of the KPI")
    max_score: float = Field(..., ge=0.0, description="Maximum possible points for this KPI")
    awarded_score: Optional[float] = Field(
        default=None,
        description="Points awarded based on evidence, or None if the underlying data is completely unknown",
    )
    effective_points: float = Field(
        default=0.0, ge=0.0, description="Actual raw points contributed before missing-data normalization"
    )
    is_known: bool = Field(
        default=False, description="True if verified data exists for this KPI; False if missing/unknown"
    )
    rationale: str = Field(..., description="Deterministic explanation for why this score was assigned")
    supporting_evidence_ids: List[str] = Field(
        default_factory=list, description="IDs of Evidence records supporting this KPI"
    )


class LeadQualification(BaseModel):
    """Complete qualification output for a prospective property management customer."""

    company_id: str = Field(..., description="Associated company ID")
    company_name: str = Field(default="", description="Associated company name")
    individual_kpi_scores: Dict[str, KPIScoreBreakdown] = Field(
        default_factory=dict, description="Per-KPI score breakdown keyed by KPI identifier"
    )
    raw_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Unadjusted sum of known KPI points")
    normalized_known_score: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Score normalized over the maximum possible known points"
    )
    total_score: float = Field(
        ..., ge=0.0, le=100.0, description="Final deterministic lead score (0-100) accounting for missing data"
    )
    lead_priority: LeadPriority = Field(..., description="Assigned priority tier (High, Medium, Low, Insufficient Information)")
    qualification_reason: str = Field(
        ..., description="Comprehensive human-readable explanation of the qualification result"
    )
    data_completeness: float = Field(
        ..., ge=0.0, le=100.0, description="Percentage (0-100%) of KPI weight backed by verified data"
    )
    confidence: str = Field(
        ..., description="Qualification confidence level (High, Medium, Low) based on completeness and evidence quality"
    )
    scoring_version: str = Field(default="1.0.0", description="Version of the KPI scoring rules applied")
    qualified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
