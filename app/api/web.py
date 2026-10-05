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

    profile = db.get(Profile, user.id)
    page = int(request.query_params.get("page", 1))
    per_page = 20
    offset = (page - 1) * per_page

    matches = []
    has_more = False
    if profile and profile.skills:
        raw = find_matches(db, user, limit=per_page + 1, offset=offset, min_score=40)
        has_more = len(raw) > per_page
        matches = raw[:per_page]

    return templates.TemplateResponse(request, "dashboard.html", _ctx(
        request, user=user, profile=profile, matches=matches,
        page=page, has_more=has_more,
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

    from app.db.models import Resume
    resume = db.query(Resume).filter_by(user_id=user.id).order_by(Resume.uploaded_at.desc()).first()

    return templates.TemplateResponse(request, "resume.html", _ctx(
        request, user=user, resume=resume,
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

    from app.social import feed_for, display_name
    from app.db.models import Follow

    posts = feed_for(db, user.id, limit=50)
    following_ids = [r.following_id for r in db.execute(select(Follow).where(Follow.follower_id == user.id)).scalars()]
    profile = db.get(Profile, user.id)

    # Suggested people (not followed, not self, limit 8)
    from app.social import search_people
    suggestions = []
    if not following_ids:
        # cold start — suggest 8 recent users
        recent = db.execute(
            select(User, Profile).join(Profile, Profile.user_id == User.id, isouter=True)
            .where(User.id != user.id).limit(8)
        ).all()
        for u, p in recent:
            suggestions.append({
                "user_id": str(u.id),
                "name": display_name(u, p),
                "title": p.title if p else None,
                "company": p.company_name if p else None,
            })

    return templates.TemplateResponse(request, "feed.html", _ctx(
        request, user=user, posts=posts, suggestions=suggestions, profile=profile,
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
    from app.db.models import Post

    posts = db.execute(
        select(Post).where(Post.user_id == target_user.id).order_by(desc(Post.created_at)).limit(50)
    ).scalars().all()

    posts_data = [_serialize_post(db, p, viewer.id if viewer else target_user.id) for p in posts]

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
            "skills": (profile.skills or []) if profile else [],
        },
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

    from app.social import inbox, unread_messages_count
    convos = inbox(db, user.id)
    unread = unread_messages_count(db, user.id)

    return templates.TemplateResponse(request, "messages.html", _ctx(
        request, user=user, convos=convos, unread=unread,
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

    return templates.TemplateResponse(request, "thread.html", _ctx(
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
        chat_theme=my_profile.chat_theme or "classic",
    ))


@router.post("/messages/{other_id}")
async def send_dm(other_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user_web(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    from uuid import UUID
    try:
        other_uuid = UUID(other_id)
    except ValueError:
        raise HTTPException(404, "invalid user id")

    form = await request.form()
    body = (form.get("body") or "").strip()
    if body:
        from app.social import send_message
        try:
            send_message(db, user.id, other_uuid, body)
        except Exception as e:
            print("dm send error:", e)

    return RedirectResponse(f"/messages/{other_id}", status_code=302)


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
    t = (body.get("theme") or "classic").strip()
    if t not in ("classic", "ocean", "forest", "sunset", "midnight", "rose", "paper"):
        t = "classic"
    profile = db.get(Profile, user.id) or Profile(user_id=user.id)
    profile.chat_theme = t
    db.add(profile)
    db.commit()
    return JSONResponse({"ok": True, "theme": t})
