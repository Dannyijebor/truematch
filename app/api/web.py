import os
from fastapi import APIRouter, Request, Form, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import User, Profile, Job
from app.auth import hash_password, verify_password, create_token, decode_token
from app.matching import find_matches

router = APIRouter()
templates = Jinja2Templates(directory="templates")

COOKIE_NAME = "tm_token"


def current_user_web(request: Request, db: Session) -> User | None:
    tok = request.cookies.get(COOKIE_NAME)
    if not tok:
        return None
    uid = decode_token(tok)
    if not uid:
        return None
    return db.get(User, uid)


def _ctx(request, **extra):
    base = {"request": request, "user": None}
    base.update(extra)
    return base


@router.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if user:
        return RedirectResponse("/app", status_code=302)
    return templates.TemplateResponse(request, "landing.html", _ctx(request))


@router.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp


@router.get("/signup", response_class=HTMLResponse)
def signup_get(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "auth.html", _ctx(request, mode="signup"))


@router.post("/signup")
def signup_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    country: str = Form("NG"),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    if len(password) < 6:
        return templates.TemplateResponse(request, "auth.html", _ctx(request, mode="signup", error="Password must be at least 6 characters."),
            status_code=400,
        )
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        return templates.TemplateResponse(request, "auth.html", _ctx(request, mode="signup", error="That email is already registered."),
            status_code=400,
        )
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name.strip() or None,
        country=country or None,
    )
    db.add(user)
    db.flush()
    db.add(Profile(user_id=user.id, skills=[], remote_ok=True))
    db.commit()

    token = create_token(str(user.id))
    resp = RedirectResponse("/app", status_code=302)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp


@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "auth.html", _ctx(request, mode="login"))


@router.post("/login")
def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "auth.html", _ctx(request, mode="login", error="Wrong email or password."),
            status_code=401,
        )
    token = create_token(str(user.id))
    resp = RedirectResponse("/app", status_code=302)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp


@router.get("/app", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    profile = db.get(Profile, user.id)
    matches = []
    if profile and profile.skills:
        matches = find_matches(db, user, limit=40, min_score=40)

    return templates.TemplateResponse(request, "dashboard.html", _ctx(request, user=user, profile=profile, matches=matches),
    )


@router.post("/app/profile")
def update_profile_web(
    request: Request,
    headline: str = Form(""),
    seniority: str = Form("mid"),
    years_experience: str = Form(""),
    location: str = Form(""),
    skills: str = Form(""),
    remote_ok: str = Form(None),
    db: Session = Depends(get_db),
):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    profile = db.get(Profile, user.id) or Profile(user_id=user.id)
    profile.headline = headline.strip() or None
    profile.seniority = seniority or "mid"
    try:
        profile.years_experience = int(years_experience) if years_experience else None
    except ValueError:
        profile.years_experience = None
    profile.location = location.strip() or None
    profile.skills = [s.strip().lower() for s in skills.split(",") if s.strip()]
    profile.remote_ok = remote_ok is not None

    db.add(profile)
    db.commit()

    return RedirectResponse("/app", status_code=302)


@router.get("/app/job/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "not found")

    from app.db.models import ApplyPacket
    packet = db.execute(
        select(ApplyPacket).where(ApplyPacket.user_id == user.id, ApplyPacket.job_id == job.id)
    ).scalar_one_or_none()

    return templates.TemplateResponse(request, "job.html", _ctx(request, user=user, job=job, packet=packet),
    )


@router.post("/app/job/{job_id}/packet")
def generate_packet_web(job_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "not found")

    profile = db.get(Profile, user.id)
    from app.matching import score_job
    from app.apply_packet import generate_packet

    score, reason = score_job(profile, job) if profile else (0, None)
    if reason is None:
        reason = {"matched_skills": [], "missing_skills": [], "job_seniority": "mid"}

    try:
        generate_packet(db, user, job, reason)
    except Exception as e:
        raise HTTPException(500, f"generation failed: {e}")

    return RedirectResponse(f"/app/job/{job_id}", status_code=302)


@router.post("/app/job/{job_id}/auto_apply_web")
def auto_apply_web(job_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "not found")
    from app.auto_apply import auto_apply_to_job
    try:
        auto_apply_to_job(db, user, job)
    except Exception as e:
        print("auto_apply error:", e)
    return RedirectResponse(f"/app/job/{job_id}", status_code=302)
