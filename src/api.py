"""FastAPI service exposing REST endpoints for the Heidi Systems B2B Lead Generation System."""

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.main import HeidiLeadPipeline
from src.models import Company, Contact, Evidence, LeadQualification

app = FastAPI(
    title="Heidi Systems B2B Lead Generation API",
    description=(
        "AI-powered B2B lead discovery, website extraction, deterministic KPI qualification, "
        "and decision-maker contact research for Berlin property management companies (Hausverwaltungen)."
    ),
    version="1.0.0",
)


class PipelineRunRequest(BaseModel):
    max_companies: int = 25
    force_refresh: bool = False
    output_filename: str = "heidi_berlin_leads.xlsx"


@app.get("/health")
def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "heidi-b2b-lead-generator"}


@app.get("/api/v1/companies", response_model=List[Company])
def list_companies() -> List[Company]:
    """Return all discovered Berlin property management companies."""
    pipeline = HeidiLeadPipeline()
    return pipeline.repository.list_companies(include_samples=False)


@app.get("/api/v1/qualifications", response_model=List[LeadQualification])
def list_qualifications(
    priority: Optional[str] = Query(default=None, description="Filter by High, Medium, Low, Insufficient Information")
) -> List[LeadQualification]:
    """Return deterministic KPI qualification results sorted by total score descending."""
    pipeline = HeidiLeadPipeline()
    quals = pipeline.repository.list_qualifications()
    if priority:
        quals = [q for q in quals if q.lead_priority.value.lower() == priority.lower()]
    return sorted(quals, key=lambda q: q.total_score, reverse=True)


@app.get("/api/v1/contacts", response_model=List[Contact])
def list_contacts() -> List[Contact]:
    """Return extracted decision-maker contacts."""
    pipeline = HeidiLeadPipeline()
    return pipeline.repository.list_contacts()


@app.get("/api/v1/evidence", response_model=List[Evidence])
def list_evidence(company_id: Optional[str] = None) -> List[Evidence]:
    """Return supporting evidence records, optionally filtered by company_id."""
    pipeline = HeidiLeadPipeline()
    if company_id:
        return pipeline.repository.get_company_evidence(company_id)
    return pipeline.repository.list_evidence()


@app.post("/api/v1/pipeline/run")
def run_pipeline(req: PipelineRunRequest) -> Dict[str, Any]:
    """Execute the full discovery, extraction, qualification, and Excel export pipeline."""
    pipeline = HeidiLeadPipeline()
    return pipeline.run_full_pipeline(
        max_companies=req.max_companies,
        force_refresh=req.force_refresh,
        output_filename=req.output_filename,
    )


@app.get("/api/v1/export/excel")
def download_excel(filename: str = "heidi_berlin_leads.xlsx") -> FileResponse:
    """Download the generated 5-sheet Excel workbook."""
    pipeline = HeidiLeadPipeline()
    file_path = pipeline.settings.output_dir / filename
    if not file_path.exists():
        file_path = pipeline.run_export_stage(output_filename=filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Excel deliverable not found.")
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
