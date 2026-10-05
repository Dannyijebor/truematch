import re
from collections import Counter
from sqlalchemy import select, desc, func, or_
from sqlalchemy.orm import Session
from app.db.models import Job, User, Profile, Company, Post
from app.resume_parser import SKILL_DICT


def top_skills_in_demand(db: Session, limit: int = 20, sample: int = 1500) -> list[dict]:
    """Scan the most recent jobs and count how often each known skill appears."""
    rows = db.execute(
        select(Job.title, Job.description_text)
        .where(Job.is_active == True, Job.confidence >= 80)
        .order_by(desc(Job.posted_at))
        .limit(sample)
    ).all()

    counter = Counter()
    for title, desc in rows:
        text = ((title or "") + " " + ((desc or "")[:2500])).lower()
        for skill in SKILL_DICT:
            if skill in text:
                counter[skill] += 1

    return [{"skill": s, "count": n} for s, n in counter.most_common(limit)]


def companies_hiring(db: Session, limit: int = 8) -> list[dict]:
    rows = db.execute(
        select(Company.id, Company.name, func.count(Job.id).label("n"))
        .join(Job, Job.company_id == Company.id)
        .where(Job.is_active == True)
        .group_by(Company.id, Company.name)
        .order_by(desc("n"))
        .limit(limit)
    ).all()
    return [{"id": str(cid), "name": name, "open": n} for cid, name, n in rows]


def recruiters_hiring_now(db: Session, limit: int = 8) -> list[dict]:
    rows = db.execute(
        select(User, Profile, func.count(Job.id).label("n"))
        .join(Job, Job.posted_by_user_id == User.id)
        .outerjoin(Profile, Profile.user_id == User.id)
        .where(Job.is_active == True)
        .group_by(User.id, Profile.user_id)
        .order_by(desc("n"))
        .limit(limit)
    ).all()

    from app.social import display_name
    out = []
    for user, profile, n in rows:
        out.append({
            "user_id": str(user.id),
            "name": display_name(user, profile),
            "username": profile.username if profile else None,
            "title": profile.title if profile else None,
            "company": profile.company_name if profile else None,
            "avatar_url": profile.avatar_url if profile else None,
            "open_roles": n,
        })
    return out


def jobs_matching_you(db: Session, user: User, limit: int = 3) -> list[dict]:
    profile = db.get(Profile, user.id)
    if not profile or not profile.skills:
        return []
    from app.matching import find_matches
    return find_matches(db, user, limit=limit, min_score=55)


def people_to_know(db: Session, user_id, limit: int = 8) -> list[dict]:
    """Suggest users whose skills overlap with the viewer's, or who work at companies hiring."""
    viewer_profile = db.get(Profile, user_id)
    viewer_skills = set((viewer_profile.skills or [])) if viewer_profile else set()

    # Get companies with active jobs
    hiring_company_ids = [
        cid for (cid,) in db.execute(
            select(Job.company_id).where(Job.is_active == True, Job.company_id.isnot(None)).distinct()
        ).all()
    ]

    # Find profiles with matching skills, excluding viewer
    candidates = db.execute(
        select(User, Profile)
        .join(Profile, Profile.user_id == User.id)
        .where(User.id != user_id)
        .limit(80)
    ).all()

    from app.social import display_name
    scored = []
    for user, profile in candidates:
        score = 0
        if profile.skills and viewer_skills:
            score += len(set(profile.skills) & viewer_skills) * 2
        if profile.company_name:
            score += 1  # having a company is a plus
        scored.append((score, user, profile))

    scored.sort(key=lambda x: -x[0])

    out = []
    for _, user, profile in scored[:limit]:
        out.append({
            "user_id": str(user.id),
            "name": display_name(user, profile),
            "username": profile.username if profile else None,
            "title": profile.title if profile else None,
            "company": profile.company_name if profile else None,
            "avatar_url": profile.avatar_url if profile else None,
            "shared_skills": list(set(profile.skills or []) & viewer_skills)[:4] if viewer_skills else [],
        })
    return out


def platform_pulse(db: Session) -> dict:
    """Big numbers for the hero."""
    total_jobs = db.execute(select(func.count()).select_from(Job).where(Job.is_active == True)).scalar() or 0
    total_users = db.execute(select(func.count()).select_from(User)).scalar() or 0
    total_posted = db.execute(select(func.count()).select_from(Job).where(Job.job_type == "posted", Job.is_active == True)).scalar() or 0
    return {"jobs": total_jobs, "users": total_users, "posted_jobs": total_posted}
