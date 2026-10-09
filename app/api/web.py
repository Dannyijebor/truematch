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

# --- Starlette signature compatibility shim ---
# Modern Starlette (>=0.29): TemplateResponse(request, name, context)
# Old Starlette (<=0.28):    TemplateResponse(name, context) — request inside context
import starlette as _starlette_mod
try:
    _sv = tuple(int(x) for x in _starlette_mod.__version__.split(".")[:2])
except Exception:
    _sv = (0, 29)

if _sv < (0, 29):
    _orig_response = templates.TemplateResponse
    def _compat_response(request, name, context=None, **kwargs):
        ctx = dict(context) if context else {}
        if "request" not in ctx:
            ctx["request"] = request
        return _orig_response(name, ctx, **kwargs)
    templates.TemplateResponse = _compat_response
# --- end shim ---

COOKIE_NAME = "tm_token"


def current_user_web(request: Request, db: Session) -> User | None:
    tok = request.cookies.get(COOKIE_NAME)
    if not tok:
        return None
    uid = decode_token(tok)
    if not uid:
        return None
    return db.get(User, uid)


def _ensure_username(db: Session, user: User, profile=None) -> Profile:
    """Ensure the user has a unique public username for their portfolio.
    Auto-generates from their name/email on first visit. Returns the Profile."""
    import re as _re, secrets as _secrets
    from app.db.models import Profile as _P

    if profile is None:
        profile = db.get(_P, user.id)
    if not profile:
        profile = _P(user_id=user.id)
        db.add(profile); db.commit(); db.refresh(profile)

    if profile.username:
        return profile

    base = (user.full_name or (user.email or "").split("@")[0] or "user").strip().lower()
    base = _re.sub(r"[^a-z0-9]+", "-", base).strip("-") or "user"
    base = base[:24]
    candidate = base
    attempt = 0
    while True:
        exists = db.query(_P).filter(_P.username == candidate, _P.user_id != user.id).first()
        if not exists:
            break
        attempt += 1
        candidate = f"{base}-{_secrets.token_hex(2)}" if attempt > 3 else f"{base}-{attempt}"
    profile.username = candidate
    db.commit(); db.refresh(profile)
    return profile


def _ctx(request, db=None, **extra):
    """Build template context. Reuses the caller's DB session if provided."""
    base = {"request": request, "user": None, "user_profile": None}
    base.update(extra)

    if base.get("user") and db is not None:
        from app.db.models import Profile
        p = db.get(Profile, base["user"].id)
        if not p:
            p = Profile(user_id=base["user"].id)
            db.add(p); db.commit(); db.refresh(p)
        base["user_profile"] = p

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
    return templates.TemplateResponse(request, "auth.html", _ctx(request, db=db, mode="signup"))


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
        return templates.TemplateResponse(request, "auth.html", _ctx(request, db=db, mode="signup", error="Password must be at least 6 characters."),
            status_code=400,
        )
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        return templates.TemplateResponse(request, "auth.html", _ctx(request, db=db, mode="signup", error="That email is already registered."),
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
    return templates.TemplateResponse(request, "auth.html", _ctx(request, db=db, mode="login"))


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
        return templates.TemplateResponse(request, "auth.html", _ctx(request, db=db, mode="login", error="Wrong email or password."),
            status_code=401,
        )
    token = create_token(str(user.id))
    next_url = request.query_params.get("next", "/app")
    if not next_url.startswith("/"):
        next_url = "/app"
    resp = RedirectResponse(next_url, status_code=302)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp


@router.get("/app", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    # GATE: no resume = no matches. Send them to build one.
    from app.db.models import Resume as _Resume
    has_resume = db.execute(
        select(_Resume).where(_Resume.user_id == user.id).limit(1)
    ).first()
    if not has_resume:
        return RedirectResponse("/app/resume?welcome=1", status_code=302)

    profile = db.get(Profile, user.id)

    # Show-more pattern: ?show=N starts at 20, grows by 20 up to 100
    try:
        show = int(request.query_params.get("show", 20))
    except (ValueError, TypeError):
        show = 20
    show = max(20, min(100, show))

    matches = []
    has_more = False
    total_found = 0
    if profile and profile.skills:
        # fetch one extra to know if there's more beyond what we show
        raw = find_matches(db, user, limit=show + 1, offset=0, min_score=30)
        has_more = len(raw) > show and show < 100
        matches = raw[:show]
        total_found = len(matches)

    from app.experiments import variant_config, track
    cta = variant_config(db, user.id, "dashboard_cta_label", default={"label": "Generate tailored application"})
    if cta.get("variant"):
        try: track(db, "dashboard_cta_label", cta["variant"], "impression", user_id=user.id)
        except Exception: pass

    layout = variant_config(db, user.id, "match_card_layout", default={"show_advice": False})
    if layout.get("variant"):
        try: track(db, "match_card_layout", layout["variant"], "impression", user_id=user.id)
        except Exception: pass

    return templates.TemplateResponse(request, "dashboard.html", _ctx(
        request, db=db, user=user, profile=profile, matches=matches,
        show=show, has_more=has_more, total_found=total_found,
        cta_label=cta["config"].get("label", "Generate tailored application"),
        cta_variant=cta.get("variant"),
        show_advice=bool(layout["config"].get("show_advice", False)),
        layout_variant=layout.get("variant"),
    ))


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

    return templates.TemplateResponse(request, "job.html", _ctx(request, db=db, user=user, job=job, packet=packet),
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


@router.post("/app/regions")
async def save_full_profile(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()

    profile = db.get(Profile, user.id) or Profile(user_id=user.id)
    profile.headline = (form.get("headline") or "").strip() or None
    profile.seniority = form.get("seniority") or "mid"

    try:
        ye = form.get("years_experience")
        profile.years_experience = int(ye) if ye else None
    except (ValueError, TypeError):
        profile.years_experience = None

    profile.location = (form.get("location") or "").strip() or None
    skills_raw = form.get("skills") or ""
    profile.skills = [s.strip().lower() for s in skills_raw.split(",") if s.strip()]
    profile.remote_ok = form.get("remote_ok") is not None
    profile.regions = list(form.getlist("regions"))

    db.add(profile)
    db.commit()
    return RedirectResponse("/app", status_code=302)





@router.get("/app/apply/{job_id}", response_class=HTMLResponse)
def apply_page(job_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        # Preserve the destination so login redirects back here
        return RedirectResponse(f"/login?next=/app/apply/{job_id}", status_code=302)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "not found")

    from app.db.models import ApplyPacket
    packet = db.execute(
        select(ApplyPacket).where(ApplyPacket.user_id == user.id, ApplyPacket.job_id == job.id)
    ).scalar_one_or_none()

    return templates.TemplateResponse(
        "apply.html",
        _ctx(request, db=db, user=user, job=job, packet=packet),
    )


@router.post("/app/job/{job_id}/mark_applied")
def mark_applied(job_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "not found")

    from app.db.models import Application
    existing = db.query(Application).filter_by(user_id=user.id, job_id=job.id).first()
    if existing:
        existing.status = "applied"
    else:
        db.add(Application(
            user_id=user.id, job_id=job.id,
            apply_type="manual", status="applied",
        ))
    db.commit()
    return RedirectResponse("/app", status_code=302)


# ---------- resume ----------
@router.get("/app/resume", response_class=HTMLResponse)
def resume_page(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/app/resume", status_code=302)

    from app.db.models import Resume, Profile
    import re as _re, secrets as _secrets

    profile = db.get(Profile, user.id)
    if not profile:
        profile = Profile(user_id=user.id)
        db.add(profile); db.commit(); db.refresh(profile)

    # Auto-generate a unique public username the first time they open this page
    if not profile.username:
        base = (user.full_name or (user.email or "").split("@")[0] or "user").strip().lower()
        base = _re.sub(r"[^a-z0-9]+", "-", base).strip("-") or "user"
        base = base[:24]
        candidate = base
        attempt = 0
        while True:
            exists = db.query(Profile).filter(Profile.username == candidate, Profile.user_id != user.id).first()
            if not exists:
                break
            attempt += 1
            candidate = f"{base}-{_secrets.token_hex(2)}" if attempt > 3 else f"{base}-{attempt}"
        profile.username = candidate
        db.commit(); db.refresh(profile)

    resume = db.query(Resume).filter_by(user_id=user.id).order_by(Resume.uploaded_at.desc()).first()

    return templates.TemplateResponse(request, "resume.html", _ctx(
        request, user=user, resume=resume, user_profile=profile,
    ))


@router.post("/app/resume/upload")
async def resume_upload(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    from app.db.models import Resume
    from app.resume_builder import extract_text, structure_resume
    from app.resume_parser import extract_skills, guess_seniority, guess_years_experience

    form = await request.form()
    file = form.get("file")

    if not file or not file.filename:
        return RedirectResponse("/app/resume?error=no-file", status_code=302)

    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        return RedirectResponse("/app/resume?error=too-large", status_code=302)

    try:
        raw = extract_text(data, file.filename)
    except Exception as e:
        return RedirectResponse(f"/app/resume?error=extract", status_code=302)

    try:
        structured = structure_resume(raw)
    except Exception as e:
        return RedirectResponse(f"/app/resume?error=structure", status_code=302)

    resume = Resume(
        user_id=user.id,
        filename=file.filename,
        raw_text=raw[:50000],
        parsed_skills=extract_skills(raw),
        structured_data=structured,
    )
    db.add(resume)

    profile = db.get(Profile, user.id) or Profile(user_id=user.id)
    merged = set(profile.skills or []) | set(extract_skills(raw))
    profile.skills = sorted(merged)
    if not profile.seniority:
        profile.seniority = guess_seniority(raw)
    if not profile.years_experience:
        profile.years_experience = guess_years_experience(raw)
    if not profile.headline and structured.get("headline"):
        profile.headline = structured["headline"]
    db.add(profile)

    db.commit()
    return RedirectResponse("/app/resume", status_code=302)


@router.post("/app/resume/paste")
async def resume_paste(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    from app.db.models import Resume
    from app.resume_builder import structure_resume
    from app.resume_parser import extract_skills, guess_seniority, guess_years_experience

    form = await request.form()
    raw = (form.get("raw_text") or "").strip()
    if len(raw) < 100:
        return RedirectResponse("/app/resume?error=too-short", status_code=302)

    try:
        structured = structure_resume(raw)
    except Exception:
        return RedirectResponse("/app/resume?error=structure", status_code=302)

    resume = Resume(
        user_id=user.id,
        filename="pasted.txt",
        raw_text=raw[:50000],
        parsed_skills=extract_skills(raw),
        structured_data=structured,
    )
    db.add(resume)

    profile = db.get(Profile, user.id) or Profile(user_id=user.id)
    merged = set(profile.skills or []) | set(extract_skills(raw))
    profile.skills = sorted(merged)
    db.add(profile)

    db.commit()
    return RedirectResponse("/app/resume", status_code=302)


@router.get("/app/resume/download")
def resume_download(request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import Response
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    from app.db.models import Resume
    from app.resume_builder import generate_docx

    resume = db.query(Resume).filter_by(user_id=user.id).order_by(Resume.uploaded_at.desc()).first()
    if not resume or not resume.structured_data:
        return RedirectResponse("/app/resume", status_code=302)

    data = generate_docx(resume.structured_data)
    name = (user.full_name or "resume").replace(" ", "_")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}_TrueMatch.docx"'},
    )


@router.post("/app/resume/tailor/{job_id}")
def resume_tailor(job_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    from app.db.models import Resume, ApplyPacket
    from app.resume_builder import tailor_resume, generate_docx, generate_job_questions

    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")

    resume = db.query(Resume).filter_by(user_id=user.id).order_by(Resume.uploaded_at.desc()).first()
    if not resume or not resume.structured_data:
        return RedirectResponse(f"/app/apply/{job_id}?error=no-resume", status_code=302)

    try:
        tailored = tailor_resume(resume.structured_data, job, db.get(Profile, user.id))
    except Exception:
        return RedirectResponse(f"/app/apply/{job_id}?error=tailor", status_code=302)

    # Save as a new resume row so original is preserved
    new_resume = Resume(
        user_id=user.id,
        filename=f"tailored_{job.title[:30].replace(' ','_')}.docx",
        raw_text=resume.raw_text,
        parsed_skills=resume.parsed_skills,
        structured_data=tailored,
    )
    db.add(new_resume)
    db.commit()

    return RedirectResponse(f"/app/apply/{job_id}", status_code=302)


@router.get("/app/resume/download-tailored/{job_id}")
def resume_download_tailored(job_id: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import Response
    from app.db.models import Resume
    from app.resume_builder import generate_docx

    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")

    # Find the tailored version (filename starts with "tailored_")
    resume = (
        db.query(Resume)
        .filter(Resume.user_id == user.id, Resume.filename.like("tailored_%"))
        .order_by(Resume.uploaded_at.desc())
        .first()
    )
    if not resume or not resume.structured_data:
        return RedirectResponse(f"/app/apply/{job_id}", status_code=302)

    data = generate_docx(resume.structured_data)
    name = (user.full_name or "resume").replace(" ", "_")
    company = (job.company.name if job.company else "job").replace(" ", "_")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}_{company}_tailored.docx"'},
    )


# ---------- social ----------
def _require_user(request, db):
    user = current_user_web(request, db)
    if not user:
        return None, RedirectResponse("/login", status_code=302)
    return user, None


@router.get("/feed", response_class=HTMLResponse)
def feed_page(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/feed", status_code=302)

    from app.social import feed_for
    from app.stories import story_groups

    posts = feed_for(db, user.id, limit=50)
    profile = db.get(Profile, user.id)
    groups = story_groups(db, user.id)

    from datetime import datetime, timezone
    return templates.TemplateResponse(request, "feed.html", _ctx(
        request, db=db, user=user, posts=posts, profile=profile,
        story_groups=groups,
        now_hour=datetime.now(timezone.utc).hour,
    ))

@router.get("/discover", response_class=HTMLResponse)
def discover_page(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/discover", status_code=302)

    from app.discover import (
        top_skills_in_demand, companies_hiring, recruiters_hiring_now,
        people_to_know, platform_pulse, jobs_matching_you,
    )

    pulse = platform_pulse(db)
    skills = top_skills_in_demand(db, limit=20, sample=1200)
    companies = companies_hiring(db, limit=8)
    recruiters = recruiters_hiring_now(db, limit=6)
    matches = jobs_matching_you(db, user, limit=3)
    people = people_to_know(db, user.id, limit=8)

    return templates.TemplateResponse(request, "discover.html", _ctx(
        request, db=db, user=user,
        pulse=pulse, skills=skills, companies=companies,
        recruiters=recruiters, matches=matches, people=people,
    ))


@router.get("/app/people", response_class=HTMLResponse)
def people_page(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/app/people", status_code=302)

    from app.social import search_people, is_following, display_name

    q = request.query_params.get("q", "").strip()
    if q:
        people = search_people(db, q, limit=40)
    else:
        # Default: recent users
        rows = db.execute(
            select(User, Profile).join(Profile, Profile.user_id == User.id, isouter=True)
            .where(User.id != user.id).limit(40)
        ).all()
        people = [{
            "user_id": str(u.id),
            "name": display_name(u, p),
            "username": p.username if p else None,
            "title": p.title if p else None,
            "company": p.company_name if p else None,
            "avatar_url": p.avatar_url if p else None,
            "bio": p.bio if p else None,
        } for u, p in rows]

    # Mark follow state
    for person in people:
        from uuid import UUID
        person["following"] = is_following(db, user.id, UUID(person["user_id"]))

    return templates.TemplateResponse(request, "people.html", _ctx(
        request, user=user, people=people, q=q,
    ))


@router.post("/app/post")
async def create_post_route(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()
    body = (form.get("body") or "").strip()
    image_url = (form.get("image_url") or "").strip() or None
    link_url = (form.get("link_url") or "").strip() or None

    if not body:
        return RedirectResponse("/app?error=empty", status_code=302)

    from app.social import create_post
    try:
        create_post(db, user.id, body, image_url=image_url, link_url=link_url)
    except Exception as e:
        return RedirectResponse(f"/app?error={e}", status_code=302)

    return RedirectResponse("/feed", status_code=302)


@router.post("/app/follow/{target_id}")
def follow_route(target_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    from app.social import follow
    from uuid import UUID
    try:
        follow(db, user.id, UUID(target_id))
    except Exception:
        pass
    referer = request.headers.get("referer", "/app/people")
    return RedirectResponse(referer, status_code=302)


@router.post("/app/unfollow/{target_id}")
def unfollow_route(target_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    from app.social import unfollow
    from uuid import UUID
    try:
        unfollow(db, user.id, UUID(target_id))
    except Exception:
        pass
    referer = request.headers.get("referer", "/app/people")
    return RedirectResponse(referer, status_code=302)


@router.post("/api/posts/{post_id}/like")
def like_route(post_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        raise HTTPException(401, "auth required")
    from app.social import toggle_like
    from uuid import UUID
    return toggle_like(db, user.id, UUID(post_id))


@router.get("/u/{username}", response_class=HTMLResponse)
def public_profile(username: str, request: Request, db: Session = Depends(get_db)):
    viewer = current_user_web(request, db)

    target_user = db.execute(select(User).join(Profile).where(Profile.username == username)).scalar_one_or_none()
    if not target_user:
        raise HTTPException(404, "user not found")

    profile = db.get(Profile, target_user.id)

    from app.social import is_following, followers_count, following_count, display_name, _serialize_post
    from app.db.models import Post, Resume, PortfolioItem

    posts = db.execute(
        select(Post).where(Post.user_id == target_user.id).order_by(desc(Post.created_at)).limit(50)
    ).scalars().all()
    posts_data = [_serialize_post(db, p, viewer.id if viewer else target_user.id) for p in posts]

    # Feed from resume
    resume = db.execute(
        select(Resume).where(Resume.user_id == target_user.id).order_by(Resume.uploaded_at.desc()).limit(1)
    ).scalar_one_or_none()
    resume_skills = (resume.parsed_skills or []) if resume else []
    seen = set()
    merged_skills = []
    for s in ((profile.skills or []) if profile else []) + resume_skills:
        k = (s or "").strip().lower()
        if k and k not in seen:
            seen.add(k)
            merged_skills.append(s)

    # Feed from portfolio
    portfolio_items = []
    portfolio_count = 0
    has_public_portfolio = False
    if profile and profile.portfolio_is_public and profile.username:
        has_public_portfolio = True
        rows = db.execute(
            select(PortfolioItem).where(PortfolioItem.user_id == target_user.id, PortfolioItem.visible == True)
            .order_by(PortfolioItem.sort_order).limit(20)
        ).scalars().all()
        portfolio_items = [{
            "id": str(i.id), "kind": i.kind, "title": i.title, "subtitle": i.subtitle,
            "description": i.description, "image_url": i.image_url, "link_url": i.link_url,
            "tags": i.tags or [],
        } for i in rows]
        portfolio_count = len(portfolio_items)

    years_exp = (profile.years_experience if profile else None) or 0
    seniority = (profile.seniority if profile else None) or None

    return templates.TemplateResponse(request, "profile_public.html", _ctx(
        request,
        user=viewer,
        target={
            "user_id": str(target_user.id),
            "name": display_name(target_user, profile),
            "username": profile.username if profile else None,
            "title": profile.title if profile else None,
            "company": profile.company_name if profile else None,
            "bio": profile.bio if profile else None,
            "avatar_url": profile.avatar_url if profile else None,
            "headline": profile.headline if profile else None,
            "location": profile.location if profile else None,
            "seniority": seniority,
            "years_experience": years_exp,
            "remote_ok": bool(profile.remote_ok) if profile else False,
            "skills": merged_skills,
            "portfolio_theme": profile.portfolio_theme if profile else "editorial",
            "portfolio_accent": (profile.portfolio_accent if profile and profile.portfolio_accent else "#10b981"),
        },
        portfolio_items=portfolio_items,
        portfolio_count=portfolio_count,
        has_public_portfolio=has_public_portfolio,
        has_resume=bool(resume),
        posts=posts_data,
        followers=followers_count(db, target_user.id),
        following=following_count(db, target_user.id),
        is_following=(is_following(db, viewer.id, target_user.id) if viewer else False),
        is_me=(viewer is not None and viewer.id == target_user.id),
    ))


# ---------- messages ----------
@router.get("/messages", response_class=HTMLResponse)
def messages_inbox(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/messages", status_code=302)

    from app.social import inbox, unread_messages_count, display_name
    from app.db.models import Follow, User as _U, Profile as _P
    convos = inbox(db, user.id)
    unread = unread_messages_count(db, user.id)

    # candidates for new chat: people I follow + recent posters
    following_ids = [r.following_id for r in db.execute(select(Follow).where(Follow.follower_id == user.id)).scalars()]
    candidates = []
    if following_ids:
        rows = db.execute(
            select(_U, _P).join(_P, _P.user_id == _U.id, isouter=True).where(_U.id.in_(following_ids)).limit(30)
        ).all()
        for u, p in rows:
            candidates.append({
                "user_id": str(u.id),
                "name": display_name(u, p),
                "title": p.title if p else None,
                "company": p.company_name if p else None,
                "avatar_url": p.avatar_url if p else None,
            })

    return templates.TemplateResponse(request, "messages.html", _ctx(
        request, db=db, user=user, convos=convos, unread=unread, candidates=candidates,
    ))


@router.get("/messages/{other_id}", response_class=HTMLResponse)
def message_thread(other_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse(f"/login?next=/messages/{other_id}", status_code=302)

    from uuid import UUID
    try:
        other_uuid = UUID(other_id)
    except ValueError:
        raise HTTPException(404, "invalid user id")

    other_user = db.get(User, other_uuid)
    if not other_user:
        raise HTTPException(404, "user not found")

    from app.social import thread, display_name
    msgs = thread(db, user.id, other_uuid)
    other_profile = db.get(Profile, other_user.id)
    my_profile = db.get(Profile, user.id) or Profile(user_id=user.id)

    return templates.TemplateResponse(request, "thread_v2.html", _ctx(
        request,
        db=db,
        user=user,
        profile=my_profile,
        other={
            "user_id": str(other_user.id),
            "name": display_name(other_user, other_profile),
            "username": other_profile.username if other_profile else None,
            "title": other_profile.title if other_profile else None,
            "company": other_profile.company_name if other_profile else None,
            "avatar_url": other_profile.avatar_url if other_profile else None,
        },
        msgs=msgs,
        chat_theme=normalize_theme(my_profile.chat_theme),
    ))


@router.post("/messages/{other_id}")
async def send_dm(other_id: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)

    from uuid import UUID
    try:
        other_uuid = UUID(other_id)
    except ValueError:
        return JSONResponse({"ok": False, "error": "bad id"}, status_code=400)

    form = await request.form()
    body = (form.get("body") or "").strip()
    if not body:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    from app.social import send_message
    try:
        msg = send_message(db, user.id, other_uuid, body)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    # Create a notification for the recipient
    try:
        from app.notify_inapp import create_notification
        sender = db.get(User, user.id)
        sender_name = sender.full_name or (sender.email.split("@")[0]) if sender else "Someone"
        create_notification(
            db, user_id=other_uuid, kind="message",
            title=f"New message from {sender_name}",
            body=body[:120],
            link=f"/messages/{user.id}",
        )
    except Exception as e:
        print("notify error:", e)

    return JSONResponse({
        "ok": True,
        "message": {
            "id": str(msg.id),
            "body": msg.body,
            "from_me": True,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }
    })


# ---------- settings / profile / avatar ----------
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/settings", status_code=302)

    profile = db.get(Profile, user.id) or Profile(user_id=user.id)
    return templates.TemplateResponse(request, "settings.html", _ctx(
        request, user=user, profile=profile,
    ))


@router.post("/app/settings/profile")
async def save_settings_profile(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()
    profile = db.get(Profile, user.id) or Profile(user_id=user.id)

    # Username — lowercase, alphanumeric + underscore only
    raw_username = (form.get("username") or "").strip().lower()
    if raw_username:
        import re
        if not re.match(r"^[a-z0-9_]{3,30}$", raw_username):
            return RedirectResponse("/settings?error=username-format", status_code=302)
        # Check uniqueness
        existing = db.query(Profile).filter(Profile.username == raw_username, Profile.user_id != user.id).first()
        if existing:
            return RedirectResponse("/settings?error=username-taken", status_code=302)
        profile.username = raw_username

    profile.bio = (form.get("bio") or "").strip() or None
    profile.title = (form.get("title") or "").strip() or None
    profile.company_name = (form.get("company_name") or "").strip() or None
    profile.headline = (form.get("headline") or "").strip() or None
    profile.location = (form.get("location") or "").strip() or None

    db.add(profile)
    db.commit()
    return RedirectResponse("/settings?saved=profile", status_code=302)


@router.post("/app/settings/avatar")
async def save_avatar(request: Request, db: Session = Depends(get_db)):
    import base64
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()
    file = form.get("avatar")
    if not file or not file.filename:
        return RedirectResponse("/settings?error=no-file", status_code=302)

    data = await file.read()
    if len(data) > 500 * 1024:
        return RedirectResponse("/settings?error=too-large", status_code=302)

    # Detect mime
    mime = "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        mime = "image/gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"

    b64 = base64.b64encode(data).decode()
    data_url = f"data:{mime};base64,{b64}"

    profile = db.get(Profile, user.id) or Profile(user_id=user.id)
    profile.avatar_url = data_url
    db.add(profile)
    db.commit()
    return RedirectResponse("/settings?saved=avatar", status_code=302)


@router.post("/app/settings/avatar/remove")
def remove_avatar(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    profile = db.get(Profile, user.id)
    if profile:
        profile.avatar_url = None
        db.commit()
    return RedirectResponse("/settings?saved=avatar-removed", status_code=302)


@router.post("/app/settings/theme")
async def save_theme(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    form = await request.form()
    theme = (form.get("theme") or "dark").strip()
    if theme not in ("dark", "light", "system"):
        theme = "dark"

    resp = RedirectResponse(request.headers.get("referer", "/settings"), status_code=302)
    resp.set_cookie("tm_theme", theme, max_age=60 * 60 * 24 * 365, httponly=False, samesite="lax")

    if user:
        profile = db.get(Profile, user.id)
        if profile:
            profile.theme = theme
            db.commit()

    return resp


# ---------- HR / recruiter ----------
def _is_recruiter(db, user):
    profile = db.get(Profile, user.id)
    return bool(profile and profile.company_name)


@router.get("/hire", response_class=HTMLResponse)
def hr_dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/hire", status_code=302)

    from app.hr import list_my_posted_jobs
    jobs = list_my_posted_jobs(db, user.id)
    profile = db.get(Profile, user.id)

    return templates.TemplateResponse(request, "hr_dashboard.html", _ctx(
        request, user=user, profile=profile, jobs=jobs,
    ))


@router.get("/hire/new", response_class=HTMLResponse)
def hr_new_job(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/hire/new", status_code=302)
    profile = db.get(Profile, user.id)
    return templates.TemplateResponse(request, "hr_post_job.html", _ctx(
        request, user=user, profile=profile, job=None,
    ))


@router.post("/hire/new")
async def hr_create_job(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()
    data = {
        "title": form.get("title"),
        "company_name": form.get("company_name"),
        "location": form.get("location"),
        "remote": form.get("remote") is not None,
        "salary_min": form.get("salary_min"),
        "salary_max": form.get("salary_max"),
        "description": form.get("description"),
        "requirements": form.get("requirements"),
    }

    from app.hr import create_posted_job
    try:
        job = create_posted_job(db, user, data)
    except Exception as e:
        return RedirectResponse(f"/hire/new?error={str(e)[:80]}", status_code=302)

    # Auto-populate profile company if missing
    profile = db.get(Profile, user.id) or Profile(user_id=user.id)
    if not profile.company_name and data.get("company_name"):
        profile.company_name = data["company_name"]
        db.add(profile)
        db.commit()

    return RedirectResponse(f"/hire/jobs/{job.id}", status_code=302)


@router.get("/hire/jobs/{job_id}", response_class=HTMLResponse)
def hr_job_detail(job_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    job = db.get(Job, job_id)
    if not job or job.posted_by_user_id != user.id:
        raise HTTPException(404, "job not found")

    from app.hr import list_applicants
    applicants = list_applicants(db, user.id, job.id)

    return templates.TemplateResponse(request, "hr_applicants.html", _ctx(
        request, user=user, job=job, applicants=applicants,
    ))


@router.post("/hire/jobs/{job_id}/close")
def hr_close_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    from app.hr import close_job
    try:
        close_job(db, user.id, job_id)
    except Exception:
        pass
    return RedirectResponse(f"/hire/jobs/{job_id}", status_code=302)


@router.post("/hire/applications/{app_id}/status")
async def hr_update_status(app_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()
    status = (form.get("status") or "").strip()

    from app.hr import update_application_status
    try:
        a = update_application_status(db, user.id, app_id, status)
        referer = request.headers.get("referer", "/hire")
        return RedirectResponse(referer, status_code=302)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/hire/applications/{app_id}/screen", response_class=HTMLResponse)
def hr_screen_applicant(app_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    from app.hr import ai_screen_applicant
    from app.db.models import Application
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(404, "application not found")

    job = db.get(Job, a.job_id)
    if not job or job.posted_by_user_id != user.id:
        raise HTTPException(403, "not yours")

    applicant = db.get(User, a.user_id)
    profile = db.get(Profile, a.user_id)
    from app.social import display_name
    name = display_name(applicant, profile) if applicant else "Applicant"

    try:
        result = ai_screen_applicant(db, user.id, app_id)
        error = None
    except Exception as e:
        result = None
        error = str(e)

    return templates.TemplateResponse(request, "hr_screen.html", _ctx(
        request, user=user, job=job, applicant_id=str(a.user_id),
        applicant_name=name, result=result, error=error, app_id=app_id,
    ))


@router.get("/jobs-posted", response_class=HTMLResponse)
def public_posted_jobs(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    from app.hr import list_posted_jobs_public
    jobs = list_posted_jobs_public(db, limit=200)
    return templates.TemplateResponse(request, "posted_jobs.html", _ctx(
        request, user=user, jobs=jobs,
    ))


@router.post("/app/settings/chat_theme")
async def save_chat_theme(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    t = (form.get("chat_theme") or "classic").strip()
    if t not in ("classic", "ocean", "forest", "sunset", "midnight", "rose", "paper"):
        t = "classic"
    profile = db.get(Profile, user.id) or Profile(user_id=user.id)
    profile.chat_theme = t
    db.add(profile)
    db.commit()
    referer = request.headers.get("referer", "/messages")
    return RedirectResponse(referer, status_code=302)


CHAT_THEMES = ("executive", "boardroom", "heritage", "sovereign", "obsidian", "bordeaux", "editorial")
LEGACY_THEME_MAP = {
    "classic": "executive", "ocean": "boardroom", "forest": "heritage",
    "sunset": "sovereign", "midnight": "obsidian", "rose": "bordeaux", "paper": "editorial",
}


def normalize_theme(t: str | None) -> str:
    t = (t or "executive").strip().lower()
    t = LEGACY_THEME_MAP.get(t, t)
    return t if t in CHAT_THEMES else "executive"


@router.post("/api/settings/chat_theme")
async def api_save_chat_theme(request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    t = normalize_theme(body.get("theme"))
    profile = db.get(Profile, user.id) or Profile(user_id=user.id)
    profile.chat_theme = t
    db.add(profile)
    db.commit()
    return JSONResponse({"ok": True, "theme": t})


@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/notifications", status_code=302)

    from app.notify_inapp import list_notifications, mark_all_read
    items = list_notifications(db, user.id, limit=100)
    mark_all_read(db, user.id)

    return templates.TemplateResponse(request, "notifications.html", _ctx(
        request, db=db, user=user, items=items,
    ))


@router.get("/api/notifications/unread")
def api_notifications_unread(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return {"unread": 0}
    from app.notify_inapp import unread_count
    return {"unread": unread_count(db, user.id)}


# ---------- experiments admin ----------
def _is_admin(user: User) -> bool:
    return bool(user and user.email and user.email.lower() in {
        "dannyijebor@gmail.com",
    })


@router.get("/admin/experiments", response_class=HTMLResponse)
def admin_experiments(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user or not _is_admin(user):
        raise HTTPException(403, "not allowed")

    from app.experiments import stats, feedback_summary, recent_feedback
    from app.db.models import ExperimentVariant
    from sqlalchemy import select as _sel

    experiments = [r.experiment for r in db.execute(
        _sel(ExperimentVariant.experiment).distinct()
    ).scalars().all()]

    exp_data = []
    for e in experiments:
        exp_data.append({
            "name": e,
            "stats": stats(db, e, days=30),
            "variants": [
                {
                    "variant": v.variant,
                    "weight": v.weight,
                    "is_control": v.is_control,
                    "config": v.config or {},
                }
                for v in db.execute(
                    _sel(ExperimentVariant).where(ExperimentVariant.experiment == e)
                ).scalars().all()
            ],
        })

    fb = feedback_summary(db, days=30)
    recent = recent_feedback(db, limit=30)

    return templates.TemplateResponse(request, "admin_experiments.html", _ctx(
        request, db=db, user=user,
        experiments=exp_data, feedback=fb, recent=recent,
    ))


@router.post("/admin/experiments/{experiment}/promote")
def admin_promote(experiment: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user or not _is_admin(user):
        raise HTTPException(403, "not allowed")
    from app.experiments import auto_promote_if_winner
    auto_promote_if_winner(db, experiment)
    referer = request.headers.get("referer", "/admin/experiments")
    return RedirectResponse(referer, status_code=302)


@router.post("/admin/experiments/{experiment}/reset")
def admin_reset(experiment: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user or not _is_admin(user):
        raise HTTPException(403, "not allowed")
    from app.db.models import ExperimentStat
    db.query(ExperimentStat).filter(ExperimentStat.experiment == experiment).delete()
    db.commit()
    referer = request.headers.get("referer", "/admin/experiments")
    return RedirectResponse(referer, status_code=302)


# ---------- portfolio ----------
@router.get("/portfolio", response_class=HTMLResponse)
def portfolio_home(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/portfolio", status_code=302)
    return RedirectResponse("/portfolio/edit", status_code=302)


@router.get("/portfolio/edit", response_class=HTMLResponse)
def portfolio_edit(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login?next=/portfolio/edit", status_code=302)

    from app.portfolio import get_portfolio_settings, list_items, THEMES, KINDS, ACCENTS

    # Ensure the user has a public username (auto-generate on first visit)
    profile = _ensure_username(db, user)

    settings = get_portfolio_settings(db, user.id)
    items = list_items(db, user.id)

    return templates.TemplateResponse(request, "portfolio_edit.html", _ctx(
        request, db=db, user=user, settings=settings, items=items,
        themes=THEMES, kinds=KINDS, accents=ACCENTS,
        profile=profile,
    ))


@router.post("/portfolio/settings")
async def portfolio_save_settings(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()
    data = {
        "theme": form.get("theme"),
        "tagline": form.get("tagline"),
        "about": form.get("about"),
        "accent": form.get("accent"),
        "is_public": form.get("is_public") is not None,
    }
    hero = form.get("hero_image")
    if hero and hasattr(hero, "read"):
        raw = await hero.read()
        if raw and len(raw) <= 800 * 1024:
            import base64
            mime = "image/jpeg"
            if raw[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
                mime = "image/webp"
            data["hero_image"] = f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    from app.portfolio import save_portfolio_settings
    save_portfolio_settings(db, user.id, data)
    return RedirectResponse("/portfolio/edit?saved=1", status_code=302)


@router.post("/portfolio/items/add")
async def portfolio_add_item(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()
    data = {
        "kind": form.get("kind"),
        "title": form.get("title"),
        "subtitle": form.get("subtitle"),
        "description": form.get("description"),
        "link_url": form.get("link_url"),
        "tags": form.get("tags"),
        "start_date": form.get("start_date"),
        "end_date": form.get("end_date"),
    }

    img = form.get("image")
    if img and hasattr(img, "read"):
        raw = await img.read()
        if raw and len(raw) <= 800 * 1024:
            import base64
            mime = "image/jpeg"
            if raw[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
                mime = "image/webp"
            data["image_url"] = f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    from app.portfolio import add_item
    try:
        add_item(db, user.id, data)
    except Exception as e:
        return RedirectResponse(f"/portfolio/edit?error={str(e)[:60]}", status_code=302)

    return RedirectResponse("/portfolio/edit?saved=item", status_code=302)


@router.post("/portfolio/items/{item_id}/delete")
def portfolio_delete_item(item_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    from uuid import UUID
    from app.portfolio import delete_item
    try:
        delete_item(db, user.id, UUID(item_id))
    except Exception:
        pass
    return RedirectResponse("/portfolio/edit", status_code=302)


@router.post("/portfolio/items/{item_id}/toggle")
def portfolio_toggle_item(item_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    from uuid import UUID
    from app.portfolio import toggle_item_visibility
    try:
        toggle_item_visibility(db, user.id, UUID(item_id))
    except Exception:
        pass
    return RedirectResponse("/portfolio/edit", status_code=302)


@router.post("/portfolio/items/{item_id}/move")
async def portfolio_move_item(item_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    form = await request.form()
    direction = form.get("direction") or "up"
    from uuid import UUID
    from app.portfolio import move_item
    try:
        move_item(db, user.id, UUID(item_id), direction)
    except Exception:
        pass
    return RedirectResponse("/portfolio/edit", status_code=302)


@router.get("/p/{username}", response_class=HTMLResponse)
def portfolio_public_view(username: str, request: Request, db: Session = Depends(get_db)):
    from app.portfolio import public_portfolio
    data = public_portfolio(db, username)
    if not data:
        raise HTTPException(404, "Portfolio not found or not public")

    viewer = current_user_web(request, db)
    return templates.TemplateResponse(request, "portfolio_public.html", _ctx(
        request, db=db, user=viewer, **data,
    ))


# ---------- stories ----------
@router.post("/stories/create")
async def story_create(request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    form = await request.form()
    kind = (form.get("kind") or "text").lower()
    body = form.get("body") or ""
    background = (form.get("background") or "aurora").strip()

    image_url = None
    img = form.get("image")
    if kind == "image" and img and hasattr(img, "read"):
        raw = await img.read()
        if raw and len(raw) <= 900 * 1024:
            import base64
            mime = "image/jpeg"
            if raw[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
                mime = "image/webp"
            image_url = f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    from app.stories import create_story
    try:
        create_story(db, user.id, kind, body=body, image_url=image_url, background=background)
    except Exception as e:
        return RedirectResponse(f"/feed?error={str(e)[:60]}", status_code=302)

    return RedirectResponse("/feed?posted=story#experiences", status_code=302)


@router.post("/stories/{story_id}/delete")
def story_delete(story_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    from uuid import UUID
    from app.stories import delete_story
    try:
        delete_story(db, user.id, UUID(story_id))
    except Exception:
        pass
    return RedirectResponse("/feed", status_code=302)


@router.post("/api/stories/{story_id}/seen")
def story_seen(story_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return {"ok": False}
    from uuid import UUID
    from app.stories import mark_seen
    try:
        mark_seen(db, user.id, UUID(story_id))
    except Exception:
        pass
    return {"ok": True}


# ---------- post edit / delete ----------
@router.post("/api/posts/{post_id}/edit")
async def api_edit_post(post_id: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    from uuid import UUID
    try:
        body = await request.json()
    except Exception:
        body = {}
    new_body = body.get("body") or ""
    from app.social import update_post
    try:
        p = update_post(db, user.id, UUID(post_id), new_body)
        return JSONResponse({"ok": True, "body": p.body})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/api/posts/{post_id}/delete")
def api_delete_post(post_id: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    from uuid import UUID
    from app.social import delete_post
    try:
        delete_post(db, user.id, UUID(post_id))
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# ---------- story edit ----------
@router.post("/api/stories/{story_id}/edit")
async def api_edit_story(story_id: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    from uuid import UUID
    try:
        body = await request.json()
    except Exception:
        body = {}
    from app.stories import update_story
    try:
        s = update_story(db, user.id, UUID(story_id),
                         new_body=body.get("body"),
                         new_background=body.get("background"))
        return JSONResponse({
            "ok": True,
            "body": s.body,
            "background": s.background,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# ---------- media presign ----------
@router.post("/api/media/presign")
async def media_presign(request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)

    from app.media import presign_upload
    try:
        result = presign_upload(
            user_id=user.id,
            filename=body.get("filename") or "file",
            content_type=(body.get("content_type") or "").strip(),
            size=int(body.get("size") or 0),
            kind=(body.get("kind") or "").strip(),
        )
        return JSONResponse({"ok": True, **result})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# Alias — matches the JS in feed.html
@router.post("/api/stories/{story_id}/delete")
def api_story_delete(story_id: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    from uuid import UUID
    from app.stories import delete_story
    try:
        delete_story(db, user.id, UUID(story_id))
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


# ---------- chat send + stickers + voice ----------
@router.post("/api/chat/send")
async def api_chat_send(request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)

    to_id = body.get("to")
    kind = body.get("kind") or "text"
    text = body.get("body") or ""
    media_url = body.get("media_url")
    duration = body.get("media_duration")
    reply_to = body.get("reply_to_id")

    from uuid import UUID
    try:
        to_uuid = UUID(to_id)
    except Exception:
        return JSONResponse({"ok": False, "error": "bad recipient"}, status_code=400)

    reply_uuid = None
    if reply_to:
        try: reply_uuid = UUID(reply_to)
        except Exception: pass

    from app.social import send_message
    try:
        msg = send_message(db, user.id, to_uuid, body=text, kind=kind,
                           media_url=media_url,
                           media_duration=(float(duration) if duration else None),
                           reply_to_id=reply_uuid)

        # Create notification for recipient
        try:
            from app.notify_inapp import create_notification
            sender_name = user.full_name or user.email.split("@")[0]
            preview = text if kind == "text" else (
                "sent an image" if kind == "image" else
                "sent a voice message" if kind == "voice" else
                "sent a sticker")
            create_notification(
                db, user_id=to_uuid, kind="message",
                title=f"New message from {sender_name}",
                body=(preview[:120] if text else preview),
                link=f"/messages/{user.id}",
            )
        except Exception:
            pass

        # Build reply preview if this message replies to another
        reply_obj = None
        if reply_uuid:
            try:
                from app.db.models import DirectMessage as _DM
                parent = db.get(_DM, reply_uuid)
                if parent:
                    if parent.kind == "image":
                        preview = "[image]"
                    elif parent.kind == "voice":
                        preview = "[voice]"
                    elif parent.kind == "sticker":
                        preview = parent.body or "[sticker]"
                    else:
                        preview = (parent.body or "")[:80]
                    reply_obj = {
                        "id": str(parent.id),
                        "preview": preview,
                        "from_me": parent.from_user_id == user.id,
                    }
            except Exception:
                reply_obj = None

        return JSONResponse({
            "ok": True,
            "message": {
                "id": str(msg.id),
                "body": msg.body,
                "kind": msg.kind,
                "media_url": msg.media_url,
                "media_duration": msg.media_duration,
                "from_me": True,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "read": False,
                "delivered": False,
                "reply": reply_obj,
            }
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/api/chat/messages/{message_id}/edit")
async def api_edit_message(message_id: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    from uuid import UUID
    from app.db.models import DirectMessage
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
    text = (body.get("body") or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)
    try:
        m = db.get(DirectMessage, UUID(message_id))
        if not m or m.from_user_id != user.id:
            return JSONResponse({"ok": False, "error": "not yours"}, status_code=403)
        if m.kind != "text":
            return JSONResponse({"ok": False, "error": "only text editable"}, status_code=400)
        m.body = text[:4000]
        db.commit()
        return JSONResponse({"ok": True, "body": m.body})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/api/chat/messages/{message_id}/delete")
def api_delete_message(message_id: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    from uuid import UUID
    from app.social import delete_message_for_me
    try:
        delete_message_for_me(db, user.id, UUID(message_id))
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.get("/api/stickers")
def api_list_stickers(request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "items": []})
    from app.social import list_stickers
    return JSONResponse({"ok": True, "items": list_stickers(db, user.id)})


@router.post("/api/stickers")
async def api_save_sticker(request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
    from app.social import toggle_sticker
    try:
        result = toggle_sticker(db, user.id,
            name=(body.get("name") or "").strip() or "sticker",
            kind=body.get("kind") or "emoji",
            data=body.get("data") or "")
        return JSONResponse({"ok": True, **result})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/api/stickers/{sticker_id}/delete")
def api_delete_sticker(sticker_id: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    from uuid import UUID
    from app.social import delete_sticker
    try:
        delete_sticker(db, user.id, UUID(sticker_id))
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/api/chat/clear/{other_id}")
def api_chat_clear(other_id: str, request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    from uuid import UUID
    from app.db.models import DirectMessage
    from sqlalchemy import or_, and_
    try:
        other_uuid = UUID(other_id)
    except Exception:
        return JSONResponse({"ok": False, "error": "bad id"}, status_code=400)

    db.query(DirectMessage).filter(
        or_(
            and_(DirectMessage.from_user_id == user.id, DirectMessage.to_user_id == other_uuid),
            and_(DirectMessage.from_user_id == other_uuid, DirectMessage.to_user_id == user.id),
        )
    ).delete(synchronize_session=False)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/api/chat/report")
async def api_chat_report(request: Request, db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user = current_user_web(request, db)
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    # Log to Telegram (best effort)
    try:
        import os, httpx
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if token and chat_id:
            text = f"⚠️ Report from {user.email}\\nTarget: {body.get('name','?')} ({body.get('user_id','?')})\\nReason: {body.get('reason','')[:400]}"
            httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception:
        pass
    return JSONResponse({"ok": True})
