import os
import json
import time
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Job, Profile, User, Resume, ApplyPacket

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

SYSTEM_PROMPT = """You are TrueMatch, a world-class career coach and writer.
You produce application materials that get interviews.

ABSOLUTE RULES:
1. NEVER invent employers, dates, degrees, certifications, or skills.
2. Only reference skills and experiences explicitly present in the CANDIDATE block.
3. Mirror keywords from the JOB block naturally - do not keyword stuff.
4. Be specific and quantified when the source material allows it.
5. Keep the cover letter under 320 words.
6. Output ONLY valid JSON matching the schema. No prose outside JSON.

SCHEMA:
{
  "tailored_bullets": ["<5 punchy resume bullets>"],
  "cover_letter": "<3 short paragraphs, no 'Dear Hiring Manager'>",
  "screening_answers": {
    "why_this_role": "<1-2 sentences>",
    "years_relevant": "<number as string>",
    "notice_period": "<1 line>"
  },
  "gaps": ["<required skills the candidate lacks>"],
  "keywords_hit": ["<keywords from job mirrored in the output>"]
}

STYLE GUIDE FOR BULLETS:
- Start with a strong verb (Built, Led, Shipped, Reduced, Scaled).
- Include a metric when possible (%, count, time saved).
- One line, 18-28 words. No fluff.

EXAMPLE GOOD BULLET:
"Shipped a real-time billing pipeline in Python + Kafka handling 12M events/day with 99.98% uptime."

EXAMPLE BAD BULLET:
"Responsible for various backend tasks and worked with the team on projects."
"""


def _build_user_prompt(profile, resume_text, job, match_reason):
    matched = match_reason.get("matched_skills", [])
    missing = match_reason.get("missing_skills", [])
    skills_csv = ", ".join(profile.skills or [])
    resume_snippet = (resume_text or "")[:6000]

    return f"""CANDIDATE
Headline: {profile.headline or 'N/A'}
Seniority: {profile.seniority or 'mid'}
Years: {profile.years_experience or 'N/A'}
Location: {profile.location or 'N/A'} | Remote OK: {profile.remote_ok}
Skills: {skills_csv}

RESUME EXCERPT
{resume_snippet}

JOB
Title: {job.title}
Company: {job.company.name if job.company else 'N/A'}
Location: {job.location or 'N/A'} | Remote: {job.remote}
Description:
{(job.description_text or '')[:6000]}

MATCH ANALYSIS
Matched skills: {', '.join(matched) or 'none'}
Missing skills: {', '.join(missing) or 'none'}
Job seniority: {match_reason.get('job_seniority', 'mid')}

If years_relevant is unknown, use the CANDIDATE Years value above - never output "0" unless the candidate truly has no experience.
If years_relevant is unknown, use the CANDIDATE Years value above - never output "0" unless the candidate truly has no experience.

Return ONLY the JSON object per the schema.
"""


def _call_groq(system, user, max_tokens=2500, temperature=0.4, retries=3):
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY missing")

    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    last_err = None
    for attempt in range(retries):
        try:
            r = httpx.post(GROQ_URL, headers=headers, json=body, timeout=90)
            if r.status_code == 429:
                time.sleep(2 ** attempt + 1)
                last_err = "rate limited"
                continue
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return json.loads(content), usage
        except Exception as e:
            last_err = str(e)
            time.sleep(1 + attempt)
    raise RuntimeError(f"groq call failed after {retries} tries: {last_err}")


REQUIRED_KEYS = {"tailored_bullets", "cover_letter", "screening_answers", "gaps", "keywords_hit"}


def _validate_packet(packet, user_skills, resume_text):
    if not isinstance(packet, dict):
        return None
    for k in REQUIRED_KEYS:
        if k not in packet:
            return None

    bullets = packet.get("tailored_bullets") or []
    if not isinstance(bullets, list):
        return None

    lowered_resume = (resume_text or "").lower()
    skills_lower = {s.lower() for s in (user_skills or [])}

    safe_bullets = []
    for b in bullets:
        if not isinstance(b, str) or len(b) < 20:
            continue
        bl = b.lower()
        hallucinated = False
        for token in ["kubernetes", "terraform", "golang", "rust", "pytorch", "tensorflow"]:
            if token in bl and token not in lowered_resume and token not in skills_lower:
                hallucinated = True
                break
        if hallucinated:
            continue
        safe_bullets.append(b.strip())

    packet["tailored_bullets"] = safe_bullets[:5]
    cl = packet.get("cover_letter") or ""
    if len(cl.split()) > 400:
        packet["cover_letter"] = " ".join(cl.split()[:400])

    return packet


def generate_packet(db: Session, user: User, job: Job, match_reason: dict, force: bool = False) -> ApplyPacket:
    existing = db.execute(
        select(ApplyPacket).where(
            ApplyPacket.user_id == user.id,
            ApplyPacket.job_id == job.id,
        )
    ).scalar_one_or_none()

    if existing and not force:
        return existing
    if existing and force:
        db.delete(existing)
        db.commit()

    profile = db.get(Profile, user.id)
    if not profile:
        raise RuntimeError("no profile for user")

    resume = db.execute(
        select(Resume).where(Resume.user_id == user.id).order_by(Resume.uploaded_at.desc())
    ).scalar_one_or_none()
    resume_text = resume.raw_text if resume else ""

    user_prompt = _build_user_prompt(profile, resume_text, job, match_reason)
    packet, usage = _call_groq(SYSTEM_PROMPT, user_prompt)
    packet = _validate_packet(packet, profile.skills or [], resume_text)
    if not packet:
        raise RuntimeError("invalid or empty packet from model")

    row = ApplyPacket(
        user_id=user.id,
        job_id=job.id,
        tailored_bullets=packet.get("tailored_bullets", []),
        cover_letter=packet.get("cover_letter"),
        screening_answers=packet.get("screening_answers", {}),
        gaps=packet.get("gaps", []),
        keywords_hit=packet.get("keywords_hit", []),
        model_used=MODEL,
        tokens_used=int(usage.get("total_tokens", 0)) if usage else 0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
