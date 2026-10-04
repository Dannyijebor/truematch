import re
from datetime import datetime, timezone
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from app.db.models import Job, Profile, User
from app.resume_parser import SKILL_DICT


# Map skills to role families
SKILL_TO_FAMILY = {
    # engineering
    "python": "engineering", "javascript": "engineering", "typescript": "engineering",
    "java": "engineering", "go": "engineering", "golang": "engineering",
    "rust": "engineering", "ruby": "engineering", "php": "engineering",
    "c++": "engineering", "c#": "engineering", "kotlin": "engineering",
    "swift": "engineering", "scala": "engineering", "react": "engineering",
    "vue": "engineering", "angular": "engineering", "node": "engineering",
    "node.js": "engineering", "django": "engineering", "flask": "engineering",
    "fastapi": "engineering", "rails": "engineering", "spring": "engineering",
    ".net": "engineering", "graphql": "engineering", "docker": "engineering",
    "kubernetes": "engineering", "k8s": "engineering", "terraform": "engineering",
    "aws": "engineering", "azure": "engineering", "gcp": "engineering",
    "postgresql": "engineering", "postgres": "engineering", "mysql": "engineering",
    "mongodb": "engineering", "redis": "engineering", "git": "engineering",
    "linux": "engineering", "microservices": "engineering",
    # data / ml
    "pandas": "data", "numpy": "data", "scikit-learn": "data",
    "tensorflow": "data", "pytorch": "data", "spark": "data",
    "airflow": "data", "dbt": "data", "snowflake": "data",
    "bigquery": "data", "machine learning": "data", "ml": "data",
    "nlp": "data", "computer vision": "data", "tableau": "data",
    "power bi": "data", "looker": "data",
    # design / product
    "figma": "design", "ui": "design", "ux": "design",
}

ENGINEER_TITLE_HINTS = [
    "engineer", "developer", "programmer", "swe", "sde",
    "architect", "devops", "sre", "platform", "backend",
    "frontend", "fullstack", "full-stack", "full stack",
    "mobile", "ios", "android", "data scientist", "data engineer",
    "machine learning", "ml engineer", "ai engineer",
]
NON_ENGINEER_BLOCK = [
    "administrative", "business partner", "partnerships",
    "recruiter", "talent", "sales", "account executive",
    "account manager", "customer success", "customer support",
    "marketing", "communications", "legal", "counsel",
    "finance", "accounting", "payroll", "hr ", "human resources",
    "office manager", "executive assistant", "receptionist",
    "content writer", "copywriter", "social media",
]


def infer_family(skills: set[str]) -> str:
    votes = {}
    for s in skills:
        fam = SKILL_TO_FAMILY.get(s)
        if fam:
            votes[fam] = votes.get(fam, 0) + 1
    if not votes:
        return "engineering"
    return max(votes.items(), key=lambda x: x[1])[0]


def job_skills(job: Job) -> set[str]:
    text = ((job.title or "") + " " + (job.description_text or "")).lower()
    found = set()
    for skill in SKILL_DICT:
        if re.search(r"\b" + re.escape(skill) + r"\b", text):
            found.add(skill)
    return found


def title_is_engineering(title: str) -> bool:
    t = (title or "").lower()
    if any(b in t for b in NON_ENGINEER_BLOCK):
        return False
    return any(h in t for h in ENGINEER_TITLE_HINTS)


def job_seniority(title: str) -> str:
    t = (title or "").lower()
    if "principal" in t or "staff" in t:
        return "principal"
    if "lead" in t or "head of" in t or "manager" in t:
        return "lead"
    if "senior" in t or "sr." in t:
        return "senior"
    if "junior" in t or "jr." in t or "intern" in t or "entry" in t:
        return "junior"
    return "mid"


SENIORITY_ORDER = {
    "intern": 0, "junior": 1, "mid": 2,
    "senior": 3, "lead": 4, "staff": 5, "principal": 6,
}


def score_job(profile: Profile, job: Job) -> tuple[float, dict] | tuple[None, None]:
    user_skills = set(s.lower() for s in (profile.skills or []))
    if not user_skills:
        return None, None

    user_family = infer_family(user_skills)

    # Only apply role filter for engineering users
    if user_family == "engineering" and not title_is_engineering(job.title):
        return None, None

    job_s = job_skills(job)
    overlap = user_skills & job_s
    if not overlap:
        return None, None

    skill_score = len(overlap) / max(len(user_skills), 1)
    if skill_score < 0.15:
        return None, None

    reasons = {
        "matched_skills": sorted(overlap),
        "missing_skills": sorted(job_s - user_skills),
    }

    js = job_seniority(job.title)
    us = profile.seniority or "mid"
    if js == us:
        seniority_score = 1.0
    else:
        diff = abs(SENIORITY_ORDER.get(js, 2) - SENIORITY_ORDER.get(us, 2))
        seniority_score = max(0.0, 1.0 - diff * 0.3)
    reasons["job_seniority"] = js
    reasons["user_seniority"] = us

    if job.remote and profile.remote_ok:
        location_score = 1.0
    elif profile.location and job.location:
        location_score = 1.0 if profile.location.lower() in job.location.lower() else 0.3
    else:
        location_score = 0.5
    reasons["remote"] = bool(job.remote)

    recency_score = 0.5
    if job.posted_at:
        days = (datetime.now(timezone.utc) - job.posted_at).days
        recency_score = max(0.0, 1.0 - days / 30.0)

    confidence_score = (job.confidence or 0) / 100.0

    total = (
        0.50 * skill_score
        + 0.20 * seniority_score
        + 0.15 * location_score
        + 0.08 * recency_score
        + 0.07 * confidence_score
    )

    reasons["skill_score"] = round(skill_score, 2)
    reasons["seniority_score"] = round(seniority_score, 2)
    reasons["location_score"] = round(location_score, 2)
    reasons["recency_score"] = round(recency_score, 2)

    return round(total * 100, 1), reasons


def find_matches(db: Session, user: User, limit: int = 30, offset: int = 0, min_score: float = 50.0) -> list[dict]:
    profile = db.get(Profile, user.id)
    if not profile:
        return []

    stmt = (
        select(Job)
        .where(Job.is_active == True, Job.confidence >= 85)
        .order_by(desc(Job.posted_at))
        .limit(500)
    )

    regions = getattr(profile, "regions", None) or []
    if regions:
        from sqlalchemy import or_
        clauses = [Job.location.ilike(f"%{r}%") for r in regions]
        stmt = stmt.where(or_(*clauses))

    jobs = db.execute(stmt).scalars().all()

    scored = []
    for job in jobs:
        score, reasons = score_job(profile, job)
        if score is not None and score >= min_score:
            scored.append((score, reasons, job))

    scored.sort(key=lambda x: x[0], reverse=True)

    page = scored[offset:offset + limit]

    return [{
        "job_id": str(job.id),
        "score": score,
        "reason": reasons,
        "title": job.title,
        "company": job.company.name if job.company else None,
        "location": job.location,
        "remote": job.remote,
        "apply_url": job.apply_url,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
    } for score, reasons, job in page]
