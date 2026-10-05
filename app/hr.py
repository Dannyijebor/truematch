import os
import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, desc, func, or_
from sqlalchemy.orm import Session
from app.db.models import Job, User, Profile, Application, Resume, Company, DirectMessage


# ---------- job posting ----------

def create_posted_job(db: Session, recruiter: User, data: dict) -> Job:
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    if not title or len(title) < 4:
        raise ValueError("title too short")
    if not description or len(description) < 50:
        raise ValueError("description too short (min 50 chars)")

    company_name = (data.get("company_name") or "").strip()
    if not company_name:
        profile = db.get(Profile, recruiter.id)
        company_name = (profile.company_name if profile else None) or "Unnamed company"

    # find or create company
    company = db.execute(select(Company).where(Company.name == company_name)).scalar_one_or_none()
    if not company:
        company = Company(name=company_name, verified=False)
        db.add(company)
        db.flush()

    job = Job(
        source="posted",
        source_id=str(uuid.uuid4()),
        job_type="posted",
        posted_by_user_id=recruiter.id,
        company_id=company.id,
        title=title,
        location=(data.get("location") or "").strip() or None,
        remote=bool(data.get("remote")),
        salary_min=_to_int(data.get("salary_min")),
        salary_max=_to_int(data.get("salary_max")),
        description_html=(data.get("description") or "").replace("\n", "<br>"),
        description_text=description,
        requirements=(data.get("requirements") or "").strip() or None,
        apply_url="",  # internal
        posted_at=datetime.now(timezone.utc),
        is_active=True,
        confidence=100,
        verify_reasons=["posted by verified recruiter"],
        dedupe_key=f"posted-{uuid.uuid4()}",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def list_my_posted_jobs(db: Session, recruiter_id) -> list[dict]:
    jobs = db.execute(
        select(Job).where(Job.posted_by_user_id == recruiter_id).order_by(desc(Job.posted_at))
    ).scalars().all()

    out = []
    for j in jobs:
        count = db.execute(
            select(func.count()).select_from(Application).where(Application.job_id == j.id)
        ).scalar() or 0
        out.append({
            "id": str(j.id),
            "title": j.title,
            "company": j.company.name if j.company else "—",
            "location": j.location,
            "remote": j.remote,
            "salary_min": j.salary_min,
            "salary_max": j.salary_max,
            "is_active": j.is_active,
            "posted_at": j.posted_at.isoformat() if j.posted_at else None,
            "applicants": count,
        })
    return out


def update_posted_job(db: Session, recruiter_id, job_id, data: dict) -> Job:
    job = db.get(Job, job_id)
    if not job or job.posted_by_user_id != recruiter_id:
        raise ValueError("job not found or not yours")
    for k in ("title", "location", "requirements"):
        if k in data and data[k] is not None:
            setattr(job, k, (data[k] or "").strip() or None)
    if "remote" in data:
        job.remote = bool(data["remote"])
    if "salary_min" in data:
        job.salary_min = _to_int(data["salary_min"])
    if "salary_max" in data:
        job.salary_max = _to_int(data["salary_max"])
    if "description" in data and data["description"]:
        job.description_text = data["description"]
        job.description_html = data["description"].replace("\n", "<br>")
    db.commit()
    db.refresh(job)
    return job


def close_job(db: Session, recruiter_id, job_id):
    job = db.get(Job, job_id)
    if not job or job.posted_by_user_id != recruiter_id:
        raise ValueError("job not found or not yours")
    job.is_active = False
    db.commit()


# ---------- applicants ----------

def list_applicants(db: Session, recruiter_id, job_id) -> list[dict]:
    job = db.get(Job, job_id)
    if not job or job.posted_by_user_id != recruiter_id:
        raise ValueError("job not found or not yours")

    apps = db.execute(
        select(Application).where(Application.job_id == job_id).order_by(desc(Application.created_at))
    ).scalars().all()

    from app.matching import score_job

    out = []
    for a in apps:
        applicant = db.get(User, a.user_id)
        profile = db.get(Profile, a.user_id)
        if not applicant:
            continue

        match_score = None
        if profile and profile.skills:
            score, reason = score_job(profile, job)
            match_score = score

        resume = db.execute(
            select(Resume).where(Resume.user_id == applicant.id).order_by(desc(Resume.uploaded_at))
        ).scalar_one_or_none()

        out.append({
            "application_id": str(a.id),
            "user_id": str(applicant.id),
            "name": applicant.full_name or (profile.username if profile else None) or applicant.email.split("@")[0],
            "username": profile.username if profile else None,
            "title": profile.title if profile else None,
            "location": profile.location if profile else None,
            "skills": (profile.skills or [])[:15] if profile else [],
            "match_score": match_score,
            "status": a.status,
            "apply_type": a.apply_type,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "has_resume": bool(resume),
            "summary": (resume.structured_data or {}).get("summary") if resume and resume.structured_data else None,
        })

    # sort by match score desc
    out.sort(key=lambda x: (x["match_score"] is None, -(x["match_score"] or 0)))
    return out


def update_application_status(db: Session, recruiter_id, application_id, status: str):
    allowed = {"pending", "reviewing", "shortlisted", "interviewing", "rejected", "hired", "applied", "needs_user", "sent", "failed"}
    if status not in allowed:
        raise ValueError("invalid status")
    a = db.get(Application, application_id)
    if not a:
        raise ValueError("application not found")
    job = db.get(Job, a.job_id)
    if not job or job.posted_by_user_id != recruiter_id:
        raise ValueError("not yours")
    a.status = status
    db.commit()
    return a


# ---------- AI screening ----------

SCREEN_SYSTEM = """You are an expert technical recruiter. Given a JOB and an APPLICANT's profile/resume,
score their fit and give a clear, honest recommendation.

ABSOLUTE RULES:
1. Base your assessment ONLY on facts provided. Never invent details.
2. Be honest about gaps — do not inflate.
3. Return ONLY valid JSON:
{
  "fit_score": 0-100,
  "recommendation": "strong_yes" | "yes" | "maybe" | "no",
  "summary": "2-3 sentence evaluation",
  "strengths": ["list of 2-4 concrete strengths"],
  "concerns": ["list of 1-3 concrete concerns"],
  "suggested_interview_questions": ["2-3 targeted questions"]
}
"""


def ai_screen_applicant(db: Session, recruiter_id, application_id) -> dict:
    a = db.get(Application, application_id)
    if not a:
        raise ValueError("application not found")
    job = db.get(Job, a.job_id)
    if not job or job.posted_by_user_id != recruiter_id:
        raise ValueError("not yours")

    applicant = db.get(User, a.user_id)
    profile = db.get(Profile, a.user_id)
    resume = db.execute(
        select(Resume).where(Resume.user_id == a.user_id).order_by(desc(Resume.uploaded_at))
    ).scalar_one_or_none()

    import httpx
    key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    job_blob = f"""Title: {job.title}
Company: {job.company.name if job.company else ''}
Location: {job.location or ''} | Remote: {job.remote}
Salary: {job.salary_min or '?'} - {job.salary_max or '?'}

Description:
{(job.description_text or '')[:4000]}

Requirements:
{(job.requirements or '')[:2000]}
"""

    cand_blob = f"""Name: {applicant.full_name or 'Anonymous'}
Title: {profile.title if profile else ''}
Company: {profile.company_name if profile else ''}
Location: {profile.location if profile else ''}
Seniority: {profile.seniority if profile else ''}
Years experience: {profile.years_experience if profile else ''}
Skills: {', '.join((profile.skills or [])[:40]) if profile else ''}
Bio: {(profile.bio or '')[:600] if profile else ''}

Resume summary: {(resume.structured_data or {}).get('summary') if resume and resume.structured_data else 'Not provided'}

Resume experience:
{json.dumps(((resume.structured_data or {}).get('experience') or [])[:3], ensure_ascii=False)[:2500] if resume and resume.structured_data else ''}
"""

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SCREEN_SYSTEM},
            {"role": "user", "content": f"JOB:\n{job_blob}\n\nAPPLICANT:\n{cand_blob}\n\nReturn ONLY the JSON."},
        ],
        "temperature": 0.3,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
    }

    r = httpx.post("https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body, timeout=60)
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


# ---------- public job listing ----------

def list_posted_jobs_public(db: Session, limit: int = 100) -> list[dict]:
    jobs = db.execute(
        select(Job)
        .where(Job.job_type == "posted", Job.is_active == True)
        .order_by(desc(Job.posted_at))
        .limit(limit)
    ).scalars().all()
    out = []
    for j in jobs:
        out.append({
            "id": str(j.id),
            "title": j.title,
            "company": j.company.name if j.company else "—",
            "location": j.location,
            "remote": j.remote,
            "salary_min": j.salary_min,
            "salary_max": j.salary_max,
            "posted_at": j.posted_at.isoformat() if j.posted_at else None,
        })
    return out
