from fastapi import FastAPI, Query, Depends, HTTPException
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import Job


app = FastAPI(title="TrueMatch API", version="0.1.0")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/stats")
def stats(db: Session = Depends(get_db)):
    total = db.execute(select(func.count(Job.id))).scalar()
    active = db.execute(select(func.count(Job.id)).where(Job.is_active == True)).scalar()
    high_conf = db.execute(
        select(func.count(Job.id)).where(Job.confidence >= 85)
    ).scalar()
    return {"total": total, "active": active, "high_confidence": high_conf}


@app.get("/jobs")
def list_jobs(
    db: Session = Depends(get_db),
    q: str | None = None,
    location: str | None = None,
    remote: bool | None = None,
    min_confidence: int = 85,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(Job).where(Job.is_active == True, Job.confidence >= min_confidence)
    if q:
        stmt = stmt.where(Job.title.ilike(f"%{q}%"))
    if location:
        stmt = stmt.where(Job.location.ilike(f"%{location}%"))
    if remote is not None:
        stmt = stmt.where(Job.remote == remote)
    stmt = stmt.order_by(desc(Job.posted_at)).limit(limit).offset(offset)

    rows = db.execute(stmt).scalars().all()
    return [{
        "id": str(j.id),
        "title": j.title,
        "company": j.company.name if j.company else None,
        "location": j.location,
        "remote": j.remote,
        "apply_url": j.apply_url,
        "posted_at": j.posted_at.isoformat() if j.posted_at else None,
        "confidence": j.confidence,
        "verify_reasons": j.verify_reasons,
    } for j in rows]


@app.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "not found")
    return {
        "id": str(job.id),
        "title": job.title,
        "company": job.company.name if job.company else None,
        "location": job.location,
        "remote": job.remote,
        "apply_url": job.apply_url,
        "description_text": job.description_text,
        "confidence": job.confidence,
    }
