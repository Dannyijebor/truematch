import hashlib
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Company, Job


def html_to_text(html):
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def dedupe_key(company, title, location):
    norm = "|".join([
        (company or "").lower().strip(),
        (title or "").lower().strip(),
        (location or "").lower().strip(),
    ])
    return hashlib.sha256(norm.encode()).hexdigest()


SCAM_SIGNALS = ["pay to apply", "whatsapp only", "send fee", "registration fee"]


def verify(job):
    score, reasons = 100, []
    if job["source"] != "greenhouse":
        score -= 15
        reasons.append("non-ATS source")
    if not job.get("apply_url"):
        return 0, ["no apply url"]
    days = 999
    if job.get("posted_at"):
        try:
            days = (datetime.now(timezone.utc) - job["posted_at"]).days
        except Exception:
            pass
    if days > 45:
        score -= 30
        reasons.append("stale > 45d")
    elif days > 30:
        score -= 15
        reasons.append("aging > 30d")
    blob = (html_to_text(job.get("description_html")) + " " + job["apply_url"]).lower()
    if any(s in blob for s in SCAM_SIGNALS):
        score -= 40
        reasons.append("scam signal")
    if len(html_to_text(job.get("description_html"))) < 200:
        score -= 20
        reasons.append("thin description")
    return max(score, 0), reasons


BATCH_SIZE = 100


def upsert_jobs(db: Session, jobs: list):
    new_count = 0
    updated = 0
    processed = 0

    for j in jobs:
        try:
            company = db.execute(
                select(Company).where(
                    Company.ats_source == j["source"],
                    Company.ats_token == j["company_name"],
                )
            ).scalar_one_or_none()
            if not company:
                company = Company(
                    name=j["company_name"].replace("-", " ").title(),
                    ats_source=j["source"],
                    ats_token=j["company_name"],
                    verified=True,
                )
                db.add(company)
                db.flush()

            conf, reasons = verify(j)
            text = html_to_text(j["description_html"])
            dk = dedupe_key(company.name, j["title"], j.get("location") or "")

            existing = db.execute(
                select(Job).where(
                    Job.source == j["source"],
                    Job.source_id == j["source_id"],
                )
            ).scalar_one_or_none()

            if existing:
                existing.title = j["title"]
                existing.location = j.get("location")
                existing.description_html = j.get("description_html")
                existing.description_text = text
                existing.apply_url = j["apply_url"]
                existing.posted_at = j.get("posted_at")
                existing.confidence = conf
                existing.verify_reasons = reasons
                existing.is_active = True
                updated += 1
            else:
                db.add(Job(
                    source=j["source"],
                    source_id=j["source_id"],
                    company_id=company.id,
                    title=j["title"],
                    location=j.get("location"),
                    remote=bool(j.get("remote")),
                    description_html=j.get("description_html"),
                    description_text=text,
                    apply_url=j["apply_url"],
                    posted_at=j.get("posted_at"),
                    confidence=conf,
                    verify_reasons=reasons,
                    dedupe_key=dk,
                    raw=j.get("raw"),
                ))
                new_count += 1

            processed += 1
            if processed % BATCH_SIZE == 0:
                db.commit()
                print(f"    committed {processed}/{len(jobs)}")

        except Exception as e:
            print(f"    skip {j.get('source_id')}: {e}")
            db.rollback()
            continue

    db.commit()
    return new_count, updated
