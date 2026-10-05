import os
from datetime import datetime, timezone
from fastapi import FastAPI, Query, Depends, HTTPException, UploadFile, File, Header, status, Request, Body
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import Job, User, Profile, Resume, Match, ApplyPacket
from app.auth import hash_password, verify_password, create_token, decode_token
from app.resume_parser import parse_resume
from app.matching import find_matches, score_job
from app.apply_packet import generate_packet
from app.notify import send_telegram, notify_match


from app.api.web import router as web_router

app = FastAPI(title="TrueMatch API", version="0.3.0")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(web_router)


# ---------- schemas ----------
class SignupIn(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    country: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class ProfileIn(BaseModel):
    headline: str | None = None
    seniority: str | None = None
    years_experience: int | None = None
    location: str | None = None
    remote_ok: bool = True
    min_salary: int | None = None
    skills: list[str] = []


# ---------- auth helpers ----------
def current_user(authorization: str = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing token")
    token = authorization.split(" ", 1)[1].strip()
    uid = decode_token(token)
    if not uid:
        raise HTTPException(401, "invalid token")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(401, "user not found")
    return user


# ---------- health & stats ----------
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/stats")
def stats(db: Session = Depends(get_db)):
    total = db.execute(select(func.count(Job.id))).scalar()
    active = db.execute(select(func.count(Job.id)).where(Job.is_active == True)).scalar()
    high = db.execute(select(func.count(Job.id)).where(Job.confidence >= 85)).scalar()
    users = db.execute(select(func.count(User.id))).scalar()
    return {"jobs": total, "active": active, "high_confidence": high, "users": users}


# ---------- auth endpoints ----------
@app.post("/users/signup")
def signup(payload: SignupIn, db: Session = Depends(get_db)):
    existing = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "email already registered")
    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        country=payload.country,
    )
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id, skills=[], remote_ok=True))
    db.commit()
    token = create_token(str(user.id))
    return {"user_id": str(user.id), "email": user.email, "token": token}


@app.post("/users/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    token = create_token(str(user.id))
    return {"user_id": str(user.id), "email": user.email, "token": token}


@app.get("/users/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.get(Profile, user.id)
    return {
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "country": user.country,
        "profile": {
            "headline": profile.headline,
            "seniority": profile.seniority,
            "years_experience": profile.years_experience,
            "location": profile.location,
            "remote_ok": profile.remote_ok,
            "min_salary": profile.min_salary,
            "skills": profile.skills or [],
        } if profile else None,
    }


@app.put("/users/me/profile")
def update_profile(payload: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.get(Profile, user.id)
    if not profile:
        profile = Profile(user_id=user.id)
        db.add(profile)
    if payload.headline is not None: profile.headline = payload.headline
    if payload.seniority is not None: profile.seniority = payload.seniority
    if payload.years_experience is not None: profile.years_experience = payload.years_experience
    if payload.location is not None: profile.location = payload.location
    profile.remote_ok = payload.remote_ok
    if payload.min_salary is not None: profile.min_salary = payload.min_salary
    profile.skills = payload.skills
    db.commit()
    return {"ok": True}


# ---------- resume ----------
@app.post("/users/me/resume")
async def upload_resume(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "file too large (max 8 MB)")

    try:
        parsed = parse_resume(data)
    except Exception as e:
        raise HTTPException(400, f"could not parse pdf: {e}")

    resume = Resume(
        user_id=user.id,
        filename=file.filename or "resume.pdf",
        raw_text=parsed["raw_text"][:50000],
        parsed_skills=parsed["skills"],
    )
    db.add(resume)

    profile = db.get(Profile, user.id)
    if not profile:
        profile = Profile(user_id=user.id)
        db.add(profile)
    merged = set(profile.skills or []) | set(parsed["skills"])
    profile.skills = sorted(merged)
    if parsed["seniority"] and not profile.seniority:
        profile.seniority = parsed["seniority"]
    if parsed["years_experience"] and not profile.years_experience:
        profile.years_experience = parsed["years_experience"]
    db.commit()

    return {
        "resume_id": str(resume.id),
        "filename": resume.filename,
        "skills_detected": parsed["skills"],
        "seniority": parsed["seniority"],
        "years_experience": parsed["years_experience"],
        "text_chars": len(parsed["raw_text"]),
    }


# ---------- matches ----------
@app.get("/users/me/matches")
def my_matches(
    limit: int = Query(30, le=100),
    min_score: float = Query(50.0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return find_matches(db, user, limit=limit, min_score=min_score)


# ---------- public jobs ----------
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
    } for j in rows]


# ---------- apply packet ----------
@app.post("/jobs/{job_id}/apply_packet")
def create_packet(
    job_id: str,
    force: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")

    profile = db.get(Profile, user.id)
    if not profile or not profile.skills:
        raise HTTPException(400, "complete your profile first")

    score, reason = score_job(profile, job)
    if reason is None:
        reason = {"matched_skills": [], "missing_skills": [], "job_seniority": "mid"}

    try:
        packet = generate_packet(db, user, job, reason, force=force)
    except Exception as e:
        raise HTTPException(500, f"generation failed: {e}")

    return {
        "packet_id": str(packet.id),
        "job": {
            "id": str(job.id),
            "title": job.title,
            "company": job.company.name if job.company else None,
            "apply_url": job.apply_url,
        },
        "tailored_bullets": packet.tailored_bullets,
        "cover_letter": packet.cover_letter,
        "screening_answers": packet.screening_answers,
        "gaps": packet.gaps,
        "keywords_hit": packet.keywords_hit,
        "model_used": packet.model_used,
        "tokens_used": packet.tokens_used,
    }


@app.get("/jobs/{job_id}/apply_packet")
def get_packet(
    job_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    packet = db.execute(
        select(ApplyPacket).where(
            ApplyPacket.user_id == user.id,
            ApplyPacket.job_id == job_id,
        )
    ).scalar_one_or_none()
    if not packet:
        raise HTTPException(404, "no packet yet - POST to generate")
    return {
        "packet_id": str(packet.id),
        "tailored_bullets": packet.tailored_bullets,
        "cover_letter": packet.cover_letter,
        "screening_answers": packet.screening_answers,
        "gaps": packet.gaps,
        "keywords_hit": packet.keywords_hit,
        "created_at": packet.created_at.isoformat() if packet.created_at else None,
    }


# ---------- notifications ----------
@app.post("/notify/test")
def notify_test(user: User = Depends(current_user)):
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not chat:
        raise HTTPException(500, "TELEGRAM_CHAT_ID not set")
    try:
        res = send_telegram(chat, "*TrueMatch is live.*\n\nAPI notifications are working.")
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "message_id": res.get("result", {}).get("message_id")}


@app.post("/jobs/{job_id}/notify")
def notify_job(
    job_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not chat:
        raise HTTPException(500, "TELEGRAM_CHAT_ID not set")

    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")

    profile = db.get(Profile, user.id)
    if not profile or not profile.skills:
        raise HTTPException(400, "complete your profile first")

    score, reason = score_job(profile, job)
    if reason is None:
        reason = {"matched_skills": [], "missing_skills": [], "job_seniority": "mid"}

    try:
        packet = generate_packet(db, user, job, reason)
    except Exception as e:
        raise HTTPException(500, f"packet failed: {e}")

    link = f"http://127.0.0.1:8000/jobs/{job_id}/apply_packet"
    company = job.company.name if job.company else "Company"

    try:
        res = notify_match(chat, job.title, company, score or 0, link)
    except Exception as e:
        raise HTTPException(500, f"telegram failed: {e}")

    return {
        "ok": True,
        "message_id": res.get("result", {}).get("message_id"),
        "packet_id": str(packet.id),
        "score": score,
    }


@app.post("/jobs/{job_id}/auto_apply")
def auto_apply_route(
    job_id: str,
    dry_run: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    from app.auto_apply import auto_apply_to_job
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    try:
        return auto_apply_to_job(db, user, job, dry_run=dry_run)
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------- response caching ----------
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as _Req
import time as _time

class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: _Req, call_next):
        start = _time.time()
        response = await call_next(request)
        elapsed_ms = (_time.time() - start) * 1000
        response.headers["X-Response-Time"] = f"{elapsed_ms:.0f}ms"

        # Long-cache static assets
        path = request.url.path
        if path.startswith("/static/") or path.endswith((".css", ".js", ".png", ".jpg", ".webp")):
            response.headers["Cache-Control"] = "public, max-age=86400"

        # Private, no-store for app pages — fresh data
        if path.startswith("/app") or path.startswith("/hire") or path.startswith("/messages"):
            response.headers["Cache-Control"] = "private, no-store"

        return response

app.add_middleware(TimingMiddleware)


# ---------- messaging ----------
from fastapi import Body
from app.calls import (
    messages_since, active_incoming, start_call, accept_call,
    decline_call, end_call, set_offer, set_answer, add_ice, get_call,
)


@app.get("/api/messages/{other_id}/poll")
def poll_messages(other_id: str, since: str | None = None,
                  user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    from uuid import UUID
    try:
        other_uuid = UUID(other_id)
    except ValueError:
        raise HTTPException(400, "bad id")
    return {"messages": messages_since(db, user.id, other_uuid, since)}


@app.get("/api/calls/incoming")
def incoming_call(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"call": active_incoming(db, user.id)}


@app.post("/api/calls/start/{other_id}")
def api_start_call(other_id: str, kind: str = "audio",
                   user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    from uuid import UUID
    try:
        c = start_call(db, user, UUID(other_id), kind)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"call_id": str(c.id), "kind": c.kind, "status": c.status}


@app.get("/api/calls/{call_id}/state")
def api_call_state(call_id: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    from uuid import UUID
    c = get_call(db, UUID(call_id))
    if not c or user.id not in (c.caller_id, c.callee_id):
        raise HTTPException(404, "not found")
    return {
        "call_id": str(c.id),
        "status": c.status,
        "kind": c.kind,
        "offer": c.offer,
        "answer": c.answer,
        "ice_caller": c.ice_caller or [],
        "ice_callee": c.ice_callee or [],
        "you_are": "caller" if c.caller_id == user.id else "callee",
    }


@app.post("/api/calls/{call_id}/offer")
def api_set_offer(call_id: str, payload: dict = Body(...),
                  user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    from uuid import UUID
    try:
        set_offer(db, UUID(call_id), user.id, payload)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/calls/{call_id}/answer")
def api_set_answer(call_id: str, payload: dict = Body(...),
                   user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    from uuid import UUID
    try:
        set_answer(db, UUID(call_id), user.id, payload)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/calls/{call_id}/ice")
def api_add_ice(call_id: str, side: str = "caller", payload: dict = Body(...),
                user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    from uuid import UUID
    try:
        add_ice(db, UUID(call_id), user.id, payload, side)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/calls/{call_id}/accept")
def api_accept(call_id: str, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    from uuid import UUID
    try:
        accept_call(db, UUID(call_id), user.id)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/calls/{call_id}/decline")
def api_decline(call_id: str, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    from uuid import UUID
    try:
        decline_call(db, UUID(call_id), user.id)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/calls/{call_id}/end")
def api_end(call_id: str, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    from uuid import UUID
    try:
        end_call(db, UUID(call_id), user.id)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ---------- experiments ----------
from pydantic import BaseModel as _BM

class TrackIn(_BM):
    experiment: str
    variant: str
    event: str
    meta: dict = {}


@app.post("/api/track")
def api_track(payload: TrackIn, request: Request,
              db: Session = Depends(get_db)):
    """Anonymous-safe event tracking."""
    from app.experiments import track
    uid = None
    try:
        # try to identify user via cookie without forcing auth
        from app.auth import decode_token
        tok = request.cookies.get("tm_token")
        if tok:
            uid_str = decode_token(tok)
            if uid_str:
                from uuid import UUID
                uid = UUID(uid_str)
    except Exception:
        pass

    if payload.event not in ("impression", "click", "convert"):
        raise HTTPException(400, "bad event")

    track(db, payload.experiment, payload.variant, payload.event, user_id=uid, meta=payload.meta)
    return {"ok": True}


class FeedbackIn(_BM):
    page: str
    sentiment: str  # up | down
    comment: str | None = None
    experiment: str | None = None
    variant: str | None = None


@app.post("/api/feedback")
def api_feedback(payload: FeedbackIn, request: Request, db: Session = Depends(get_db)):
    if payload.sentiment not in ("up", "down"):
        raise HTTPException(400, "bad sentiment")
    from app.experiments import record_feedback
    uid = None
    try:
        from app.auth import decode_token
        tok = request.cookies.get("tm_token")
        if tok:
            uid_str = decode_token(tok)
            if uid_str:
                from uuid import UUID
                uid = UUID(uid_str)
    except Exception:
        pass
    record_feedback(db, uid, payload.page[:80], payload.sentiment,
                    payload.comment, payload.experiment, payload.variant)
    return {"ok": True}


# ---------- experiments ----------
from pydantic import BaseModel as _BM

class TrackIn(_BM):
    experiment: str
    variant: str
    event: str
    meta: dict = {}


@app.post("/api/track")
def api_track(payload: TrackIn, request: Request,
              db: Session = Depends(get_db)):
    """Anonymous-safe event tracking."""
    from app.experiments import track
    uid = None
    try:
        # try to identify user via cookie without forcing auth
        from app.auth import decode_token
        tok = request.cookies.get("tm_token")
        if tok:
            uid_str = decode_token(tok)
            if uid_str:
                from uuid import UUID
                uid = UUID(uid_str)
    except Exception:
        pass

    if payload.event not in ("impression", "click", "convert"):
        raise HTTPException(400, "bad event")

    track(db, payload.experiment, payload.variant, payload.event, user_id=uid, meta=payload.meta)
    return {"ok": True}


class FeedbackIn(_BM):
    page: str
    sentiment: str  # up | down
    comment: str | None = None
    experiment: str | None = None
    variant: str | None = None


@app.post("/api/feedback")
def api_feedback(payload: FeedbackIn, request: Request, db: Session = Depends(get_db)):
    if payload.sentiment not in ("up", "down"):
        raise HTTPException(400, "bad sentiment")
    from app.experiments import record_feedback
    uid = None
    try:
        from app.auth import decode_token
        tok = request.cookies.get("tm_token")
        if tok:
            uid_str = decode_token(tok)
            if uid_str:
                from uuid import UUID
                uid = UUID(uid_str)
    except Exception:
        pass
    record_feedback(db, uid, payload.page[:80], payload.sentiment,
                    payload.comment, payload.experiment, payload.variant)
    return {"ok": True}
