import os
from datetime import datetime, timezone
from fastapi import FastAPI, Query, Depends, HTTPException, UploadFile, File, Header, status, Request, Body
from fastapi.staticfiles import StaticFiles
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

# Serve static assets (calls.js, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")

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
def current_user(request: Request, authorization: str = Header(None), db: Session = Depends(get_db)) -> User:
    token = None
    # Prefer explicit Authorization header
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    # Fall back to session cookie (set on web login)
    if not token:
        token = request.cookies.get("tm_token")
    if not token:
        raise HTTPException(401, "missing token")
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


@app.get("/api/calls/active")
def api_active_call(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.calls import active_call as _active
    data = _active(db, user.id)
    if not data:
        raise HTTPException(404, "no active call")
    return data


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
        "reaction": c.reaction,
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


@app.get("/debug-crash")
def debug_crash():
    """TEMPORARY: return the exact exception."""
    import sys, traceback
    info = {"python": sys.version}
    try:
        import starlette; info["starlette"] = starlette.__version__
    except Exception as e: info["starlette"] = f"ERR: {e}"
    try:
        import fastapi; info["fastapi"] = fastapi.__version__
    except Exception as e: info["fastapi"] = f"ERR: {e}"
    try:
        import jinja2; info["jinja2"] = jinja2.__version__
    except Exception as e: info["jinja2"] = f"ERR: {e}"

    # Try to actually render landing.html
    try:
        from app.api.web import templates, _ctx
        from starlette.requests import Request as R
        scope = {"type":"http","method":"GET","path":"/","headers":[],"query_string":b"",
                 "server":("x",80),"client":("x",0),"scheme":"https"}
        req = R(scope)
        ctx = _ctx(req)
        try:
            t = templates.TemplateResponse("landing.html", ctx)
            info["render_old_sig"] = "OK"
        except Exception as e:
            info["render_old_sig"] = f"{type(e).__name__}: {e}"
        try:
            t = templates.TemplateResponse(req, "landing.html", ctx)
            info["render_new_sig"] = "OK"
        except Exception as e:
            info["render_new_sig"] = f"{type(e).__name__}: {e}"
    except Exception as e:
        info["setup_error"] = f"{type(e).__name__}: {e}"
        info["traceback"] = traceback.format_exc()
    return info


@app.get("/debug-landing")
def debug_landing():
    """TEMPORARY: run the landing render and return any traceback."""
    import traceback
    try:
        from app.api.web import templates, _ctx, current_user_web
        from app.db.session import get_db
        from starlette.requests import Request as R
        scope = {"type":"http","method":"GET","path":"/","headers":[],"query_string":b"",
                 "server":("x",80),"client":("x",0),"scheme":"https"}
        req = R(scope)
        gen = get_db()
        db = next(gen)
        try:
            user = current_user_web(req, db)
            ctx = _ctx(req)
            # Try the same call the landing route makes
            resp = templates.TemplateResponse(req, "landing.html", ctx)
            body = resp.body.decode("utf-8", errors="replace")
            return {"ok": True, "len": len(body), "head": body[:200]}
        finally:
            try: next(gen)
            except StopIteration: pass
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}


from fastapi import Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session as _S

@app.get("/debug-home")
def debug_home(request: Request, db: _S = Depends(get_db)):
    """TEMPORARY: exact mimic of `/` route with traceback."""
    import traceback
    try:
        from app.api.web import templates, _ctx, current_user_web
        user = current_user_web(request, db)
        if user:
            return JSONResponse({"ok": True, "redirect_to": "/app", "user": str(user.id)})
        resp = templates.TemplateResponse(request, "landing.html", _ctx(request))
        return JSONResponse({"ok": True, "status": resp.status_code, "len": len(resp.body) if hasattr(resp, 'body') else None})
    except Exception as e:
        return JSONResponse({
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()
        }, status_code=200)


@app.post("/debug-login")
def debug_login(payload: LoginIn, db: Session = Depends(get_db)):
    """TEMPORARY: same body as /users/login but returns traceback on error."""
    import traceback
    try:
        email = payload.email.lower()
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not user:
            return {"ok": False, "reason": "no user", "email_tried": email}
        ok = verify_password(payload.password, user.password_hash)
        return {"ok": True, "user_found": True, "password_match": ok, "hash_prefix": user.password_hash.split("$")[0]}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}


@app.post("/api/calls/{call_id}/reaction")
def api_call_reaction(call_id: str, payload: dict = Body(...),
                       user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    from uuid import UUID
    from app.calls import set_reaction
    try:
        emoji = (payload.get("emoji") or "").strip()
        if not emoji:
            raise HTTPException(400, "emoji required")
        set_reaction(db, UUID(call_id), user.id, emoji)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/debug-template-check")
def debug_template_check():
    import pathlib
    try:
        text = pathlib.Path("templates/thread_v2.html").read_text()
        base = pathlib.Path("templates/base.html").read_text()
        calls = pathlib.Path("templates/_calls.html").read_text()
        js = pathlib.Path("static/calls.js").read_text()
    except Exception as e:
        return {"error": str(e)}
    return {
        "thread_v2_len": len(text),
        "thread_v2_has_tmVoiceState": "tmVoiceState" in text,
        "thread_v2_has_decodeAudioData": "decodeAudioData" in text,
        "base_has_tm_sound": "tm-sound.js" in base,
        "base_has_calls_include": "_calls.html" in base,
        "calls_has_incall": 'id="tm-incall"' in calls,
        "calls_has_local_video": 'id="tm-local-video"' in calls,
        "calls_js_len": len(js),
        "calls_js_has_force_display": "el.style.display = 'flex'" in js,
        "calls_js_has_video_mode": "tm-video-mode" in js,
    }

# ---------- Group call routes ----------
@app.post("/api/calls/{call_id}/invite")
def api_group_invite(call_id: str, payload: dict = Body(...),
                     user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    from uuid import UUID
    from app.calls_group import add_participant
    target = (payload or {}).get("user_id")
    if not target:
        raise HTTPException(400, "user_id required")
    try:
        add_participant(db, UUID(call_id), user.id, UUID(target))
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/calls/{call_id}/participants")
def api_group_participants(call_id: str,
                           user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    from uuid import UUID
    from app.calls_group import list_participants, is_member
    cid = UUID(call_id)
    if not is_member(db, cid, user.id):
        raise HTTPException(403, "not in this call")
    return {"participants": list_participants(db, cid)}


@app.post("/api/calls/{call_id}/join")
def api_group_join(call_id: str,
                   user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    from uuid import UUID
    from app.calls_group import join_call
    try:
        join_call(db, UUID(call_id), user.id)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/calls/{call_id}/leave")
def api_group_leave(call_id: str,
                    user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    from uuid import UUID
    from app.calls_group import leave_call
    try:
        leave_call(db, UUID(call_id), user.id)
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/calls/{call_id}/signal")
def api_group_signal(call_id: str, payload: dict = Body(...),
                     user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    from uuid import UUID
    from app.calls_group import push_signal, is_member
    cid = UUID(call_id)
    if not is_member(db, cid, user.id):
        raise HTTPException(403, "not in this call")
    to_user = (payload or {}).get("to")
    kind = (payload or {}).get("kind")
    data = (payload or {}).get("payload") or {}
    if not to_user or not kind:
        raise HTTPException(400, "to and kind required")
    push_signal(db, cid, user.id, UUID(to_user), kind, data)
    return {"ok": True}


@app.get("/api/calls/{call_id}/signals")
def api_group_signals(call_id: str, since: str | None = None,
                      user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    from uuid import UUID
    from app.calls_group import signals_for_me
    return {"signals": signals_for_me(db, UUID(call_id), user.id, since)}


@app.get("/api/calls/invites")
def api_group_invites(user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    from app.calls_group import invites_for_me
    return {"invites": invites_for_me(db, user.id)}


@app.get("/api/people/search")
def api_people_search(q: str = "", user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    from sqlalchemy import or_, func
    from app.db.models import User as U, Profile as P
    term = (q or "").strip().lower()
    if not term:
        return {"people": []}
    rows = db.execute(
        db.query(U, P).outerjoin(P, P.user_id == U.id)
        .filter(
            U.id != user.id,
            or_(
                func.lower(U.full_name).contains(term),
                func.lower(P.username).contains(term),
                func.lower(U.email).contains(term),
            )
        ).limit(12)
    ).all()
    out = []
    for u, pr in rows:
        from app.social import display_name
        out.append({
            "user_id": str(u.id),
            "name": display_name(u, pr),
            "username": pr.username if pr else None,
            "avatar_url": pr.avatar_url if pr else None,
        })
    return {"people": out}
