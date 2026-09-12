"""FastAPI application for the Career Intelligence Assistant."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .hybrid_analyzer import analyze_match
from .database import AnalysisRecord, JobRecord, ResumeRecord, create_tables, get_db
from .parser import parse_job_description, parse_job_text, parse_resume

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt"}

@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield

app = FastAPI(title="Career Intelligence API", description="Evidence-led resume and job analysis", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class TextJobRequest(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    company: str = Field(default="Company", max_length=160)
    location: str = Field(default="Not specified", max_length=160)
    description: str = Field(min_length=30, max_length=50_000)

class AnalysisRequest(BaseModel):
    resume_id: int
    job_id: int

class BatchAnalysisRequest(BaseModel):
    resume_id: int

class QuestionRequest(BaseModel):
    resume_id: int
    job_id: int
    question: str = Field(min_length=3, max_length=500)

def public_resume(record: ResumeRecord) -> dict[str, Any]:
    return {"id": record.id, "filename": record.filename, "data": record.parsed_data}

def public_job(record: JobRecord) -> dict[str, Any]:
    return {"id": record.id, "title": record.title, "company": record.company, "location": record.location, "filename": record.filename, "data": record.parsed_data}

async def parse_upload(upload: UploadFile, parser) -> dict[str, Any]:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Use a PDF, DOCX, or TXT file.")
    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Files must be 8 MB or smaller.")
    temp_path = ""
    try:
        with NamedTemporaryFile(suffix=suffix, delete=False) as temp:
            temp.write(content)
            temp_path = temp.name
        parsed = parser(temp_path)
        if not parsed.get("rawText", "").strip():
            raise HTTPException(422, "No readable text was found in the document.")
        return parsed
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)

@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/workspace")
def workspace(db: Session = Depends(get_db)) -> dict[str, Any]:
    resume = db.query(ResumeRecord).order_by(ResumeRecord.created_at.desc()).first()
    jobs = db.query(JobRecord).order_by(JobRecord.created_at.desc()).all()
    latest_by_job: dict[str, Any] = {}
    if resume:
        records = db.query(AnalysisRecord).filter(AnalysisRecord.resume_id == resume.id).order_by(AnalysisRecord.created_at.desc()).all()
        for item in records:
            latest_by_job.setdefault(str(item.job_id), item.result)
    return {"resume": public_resume(resume) if resume else None, "jobs": [public_job(job) for job in jobs], "analyses": latest_by_job}

@app.post("/api/resumes", status_code=201)
async def upload_resume(resume: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    record = ResumeRecord(filename=resume.filename or "resume", parsed_data=await parse_upload(resume, parse_resume))
    db.add(record); db.commit(); db.refresh(record)
    return public_resume(record)

@app.post("/api/jobs", status_code=201)
def create_job(payload: TextJobRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = JobRecord(title=payload.title.strip(), company=payload.company.strip() or "Company not specified", location=payload.location.strip() or "Not specified", parsed_data=parse_job_text(payload.description))
    db.add(record); db.commit(); db.refresh(record)
    return public_job(record)

@app.put("/api/jobs/{job_id}")
def update_job(job_id: int, payload: TextJobRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = db.get(JobRecord, job_id)
    if not record:
        raise HTTPException(404, "Job description not found.")
    record.title = payload.title.strip()
    record.company = payload.company.strip() or "Company not specified"
    record.location = payload.location.strip() or "Not specified"
    record.parsed_data = parse_job_text(payload.description)
    db.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).delete(synchronize_session=False)
    db.commit(); db.refresh(record)
    return public_job(record)

@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = db.get(JobRecord, job_id)
    if not record:
        raise HTTPException(404, "Job description not found.")
    db.query(AnalysisRecord).filter(AnalysisRecord.job_id == job_id).delete(synchronize_session=False)
    db.delete(record)
    db.commit()
    return {"deleted": True, "job_id": job_id}

@app.post("/api/jobs/upload", status_code=201)
async def upload_job(job: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    name = Path(job.filename or "Job").stem.replace("_", " ").replace("-", " ")
    record = JobRecord(title=name, company="Uploaded role", location="Not specified", filename=job.filename, parsed_data=await parse_upload(job, parse_job_description))
    db.add(record); db.commit(); db.refresh(record)
    return public_job(record)

@app.post("/api/analyses")
def analyze(payload: AnalysisRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    resume, job = db.get(ResumeRecord, payload.resume_id), db.get(JobRecord, payload.job_id)
    if not resume or not job:
        raise HTTPException(404, "Resume or job description not found.")
    result = analyze_match(resume.parsed_data, {**job.parsed_data, "title": job.title})
    db.add(AnalysisRecord(resume_id=resume.id, job_id=job.id, result=result)); db.commit()
    return {"analysis": result}

@app.post("/api/analyses/batch")
def analyze_all(payload: BatchAnalysisRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    resume = db.get(ResumeRecord, payload.resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found.")
    jobs = db.query(JobRecord).order_by(JobRecord.created_at.desc()).all()
    if not jobs:
        raise HTTPException(400, "Add at least one job description first.")
    results: dict[str, Any] = {}
    for job in jobs:
        result = analyze_match(resume.parsed_data, {**job.parsed_data, "title": job.title})
        results[str(job.id)] = result
        db.add(AnalysisRecord(resume_id=resume.id, job_id=job.id, result=result))
    db.commit()
    return {"analyses": results, "count": len(results)}

@app.post("/api/questions")
def ask_question(payload: QuestionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    resume, job = db.get(ResumeRecord, payload.resume_id), db.get(JobRecord, payload.job_id)
    if not resume or not job:
        raise HTTPException(404, "Resume or job description not found.")
    analysis, query = analyze_match(resume.parsed_data, {**job.parsed_data, "title": job.title}), payload.question.lower()
    if any(word in query for word in ("missing", "gap", "improve")):
        gaps = analysis["skillGaps"]["gaps"]
        answer = f"The clearest skill gaps are {', '.join(gaps[:6])}." if gaps else "No explicit skill gaps were found in the supplied documents."
        evidence = job.parsed_data.get("requirements", [])[:3]
    elif any(word in query for word in ("interview", "question", "prepare")):
        answer = "Prepare examples for: " + " ".join(q["question"] for q in analysis["interviewQuestions"][:3])
        evidence = resume.parsed_data.get("experience", [])[:2]
    elif any(word in query for word in ("strength", "align", "fit", "match")):
        strengths = analysis["keyStrengths"]
        answer = f"Your match score is {analysis['matchScore']}%. Strongest explicit matches: {', '.join(strengths) if strengths else 'none found'}."
        evidence = analysis["experienceAlignment"].get("alignedItems", [])[:3]
    else:
        answer = analysis["insights"][0]["description"] + " " + analysis["nextSteps"][0]["detail"]
        evidence = job.parsed_data.get("responsibilities", [])[:3]
    return {"answer": answer, "evidence": evidence, "grounded": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
