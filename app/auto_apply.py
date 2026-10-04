import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session
from app.db.models import Job, User, Profile, Application
from app.apply_router import detect_apply_type
from app.apply_packet import generate_packet
from app.matching import score_job
from app.notify import send_telegram


def _smtp_send(to_email, subject, body):
    u = os.getenv("SMTP_USER")
    p = os.getenv("SMTP_PASS")
    if not u or not p:
        raise RuntimeError("SMTP_USER / SMTP_PASS not set")
    msg = MIMEMultipart()
    msg["From"] = u
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
        s.login(u, p)
        s.send_message(msg)


def build_email_body(user, job, packet):
    name = user.full_name or "Applicant"
    company = job.company.name if job.company else "the team"
    subject = f"Application for {job.title}"
    body = f"""Hello {company},

I'm writing to apply for the {job.title} role.

{packet.cover_letter or ''}

Happy to jump on a call whenever suits.

Best regards,
{name}
{user.email}
"""
    return subject, body


def _record(db, user, job, apply_type, status, target_email, error):
    existing = db.query(Application).filter_by(user_id=user.id, job_id=job.id).first()
    if existing:
        existing.status = status
        existing.error = error
    else:
        db.add(Application(
            user_id=user.id, job_id=job.id,
            apply_type=apply_type, status=status,
            target_email=target_email, error=error,
        ))
    db.commit()


def auto_apply_to_job(db: Session, user: User, job: Job, dry_run: bool = False) -> dict:
    profile = db.get(Profile, user.id)
    if not profile:
        return {"ok": False, "error": "no profile"}

    score, reason = score_job(profile, job)
    if reason is None:
        reason = {"matched_skills": [], "missing_skills": [], "job_seniority": "mid"}

    packet = generate_packet(db, user, job, reason)
    info = detect_apply_type(job)

    result = {
        "ok": True,
        "job_id": str(job.id),
        "title": job.title,
        "company": job.company.name if job.company else None,
        "apply_type": info["type"],
        "packet_id": str(packet.id),
    }

    if info["type"] == "email" and info["email"]:
        result["target_email"] = info["email"]
        if dry_run:
            result["status"] = "dry_run"
            return result
        subject, body = build_email_body(user, job, packet)
        try:
            _smtp_send(info["email"], subject, body)
            result["status"] = "sent"
            _record(db, user, job, "email", "sent", info["email"], None)
            try:
                send_telegram(os.getenv("TELEGRAM_CHAT_ID"),
                    f"Applied automatically\n\n{job.title}\n{result['company'] or ''}\n\nSent to {info['email']}")
            except Exception:
                pass
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
            _record(db, user, job, "email", "failed", info["email"], str(e))
    else:
        result["status"] = "needs_user"
        result["deep_link"] = job.apply_url
        base = os.getenv("PUBLIC_BASE_URL", "https://truematch-plum.vercel.app")
        link = f"{base}/app/job/{job.id}"
        _record(db, user, job, "deep_link", "needs_user", None, None)
        try:
            send_telegram(os.getenv("TELEGRAM_CHAT_ID"),
                f"Ready to apply\n\n{job.title}\n{result['company'] or ''}\n\nYour packet is ready:\n{link}")
        except Exception:
            pass

    return result
