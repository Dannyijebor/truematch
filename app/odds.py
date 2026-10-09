"""HR-grade odds engine.

Replaces the pure tech-stack weighting in matching.py with a multi-signal
model that judges the applicant the way a human recruiter would: skills,
relevant experience, career trajectory, resume quality, education, timing,
and competition.
"""
from datetime import datetime, timezone
from app.job_families import detect_family, family_skills, family_display
from app.resume_parser import SKILL_DICT


# --- company tier (competition proxy) ---
TIER_1 = {"openai","anthropic","google","meta","apple","amazon","microsoft","nvidia",
          "netflix","tesla","stripe","databricks","snowflake","figma","coinbase",
          "cloudflare","samsara","airbnb","uber","lyft","spotify","palantir"}
TIER_2 = {"vercel","retool","linear","notion","airtable","loom","miro","canva",
          "grammarly","duolingo","pinterest","snap","revolut","monzo","wise",
          "klarna","intercom","zapier","hubspot","twitch","roblox","epicgames",
          "unity","ramp","vanta","mercury","cursor","perplexityai","sierra","harvey",
          "glean","cohere","replit","supabase","neon","railway","render","resend"}

SENIORITY_RANK = {"intern":0,"junior":1,"mid":2,"senior":3,"lead":4,"staff":5,"principal":6}

# ---- helpers ----

def _now():
    return datetime.now(timezone.utc)

def _days_since(dt):
    if not dt: return None
    if isinstance(dt, str):
        try: dt = datetime.fromisoformat(dt.replace("Z","+00:00"))
        except Exception: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return (_now() - dt).total_seconds() / 86400

def _job_family(job):
    desc = ""
    try: desc = (job.description_text or "")[:1500]
    except Exception: pass
    return detect_family(job.title or "", desc)

def _extract_required_skills(job, family):
    """Pull required/preferred skills from job text using family vocab + requirements field."""
    vocab = family_skills(family)
    text = ((job.title or "") + " " + (job.description_text or "")[:3000]).lower()
    # Family skills mentioned in the job
    mentioned = [s for s in vocab if s in text]
    # Also look for tech skills in job even for non-tech families (cross-signal)
    cross = [s for s in SKILL_DICT if s in text and s not in mentioned]
    # Requirements field, if present
    reqs = []
    try:
        r = (job.requirements or "").lower()
        if r:
            reqs = [s for s in vocab if s in r]
    except Exception:
        pass
    # Combine: mentioned = required + preferred. We split roughly:
    # first ~60% = required, remainder = preferred (heuristic since ATS text isn't structured)
    all_mentioned = list(dict.fromkeys(mentioned + cross))
    n = len(all_mentioned)
    if n == 0:
        return [], []
    cut = max(1, int(n * 0.6))
    return all_mentioned[:cut], all_mentioned[cut:]

def _user_skills(profile, resume):
    s = set()
    if profile and profile.skills:
        s |= {x.lower().strip() for x in profile.skills if x}
    if resume:
        for key in ("skills",):
            vals = None
            if isinstance(resume, dict): vals = resume.get(key)
            else: vals = getattr(resume, key, None)
            if vals:
                s |= {x.lower().strip() for x in vals if x}
    return s


# ---- signals ----
# Each returns (contribution_points, reason_string, fix_action_or_None)

def _sig_skill_coverage(job, profile, resume, family):
    required, preferred = _extract_required_skills(job, family)
    have = _user_skills(profile, resume)
    if not required and not preferred:
        return 0, "Job description is too thin to assess skills.", None
    req_hits = [s for s in required if s in have]
    pref_hits = [s for s in preferred if s in have]
    req_pct = len(req_hits) / max(1, len(required))
    pref_pct = len(pref_hits) / max(1, len(preferred))
    # Required dominates (75%), preferred is bonus (25%)
    pct = 0.75 * req_pct + 0.25 * pref_pct
    contrib = int(round(40 * pct))
    missing_req = [s for s in required if s not in have]
    if missing_req:
        reason = f"{len(req_hits)} of {len(required)} required skills matched. Missing: {', '.join(missing_req[:3])}"
        fix = f"Add a project or bullet showing {missing_req[0]}"
    else:
        reason = f"All {len(required)} required skills matched, plus {len(pref_hits)} preferred."
        fix = None
    return contrib, reason, fix

def _sig_years_experience(job, profile):
    yrs = None
    if profile: yrs = profile.years_experience
    # Try to read required years from job text
    text = ((job.description_text or "")[:3000]).lower()
    need_lo, need_hi = 0, 99
    import re
    m = re.search(r"(\d+)\s*(?:\+|to|-)\s*(\d+)?\s*(?:years|yrs)", text)
    if m:
        need_lo = int(m.group(1))
        need_hi = int(m.group(2)) if m.group(2) else need_lo + 5
    else:
        m = re.search(r"(\d+)\s*\+?\s*(?:years|yrs)", text)
        if m:
            need_lo = int(m.group(1)); need_hi = need_lo + 5
    if yrs is None:
        return 0, "Add your years of experience to your profile to sharpen this signal.", "Set years of experience in Settings → Profile"
    if need_lo == 0 and need_hi == 99:
        contrib = 8
        return contrib, f"No explicit experience requirement; you have {yrs} yrs.", None
    if need_lo <= yrs <= need_hi:
        return 15, f"Your {yrs} yrs fits the {need_lo}-{need_hi} yr band.", None
    if yrs < need_lo:
        gap = need_lo - yrs
        return max(-8, -3 - gap), f"You have {yrs} yrs, role asks {need_lo}-{need_hi}. {gap} yr gap.", f"Focus on roles asking {max(0, need_lo-2)}-{need_hi} yrs, or highlight adjacent experience."
    # overqualified
    return 5, f"You have {yrs} yrs (role asks {need_lo}-{need_hi}). Strong experience, watch for 'overqualified' filter.", "Frame as 'hands-on, no ego, want to build' in your cover letter."

def _sig_seniority(job, profile):
    user_lv = None
    if profile and profile.seniority: user_lv = profile.seniority
    job_lv = _job_seniority_from_title(job.title)
    if not user_lv or not job_lv: return 5, "Seniority signal skipped — set yours in profile.", "Set your seniority in Settings → Profile"
    u = SENIORITY_RANK.get(user_lv, 2); j = SENIORITY_RANK.get(job_lv, 2)
    diff = u - j
    if diff == 0: return 8, f"Seniority matches ({user_lv}).", None
    if diff == 1: return 6, f"You're 1 level above ({user_lv} → {job_lv}). Usually fine.", None
    if diff >= 2: return -3, f"You're {diff} levels above ({user_lv} → {job_lv}). Overqualified penalty.", "Target {}-level roles.".format(user_lv)
    if diff == -1: return 4, f"You're 1 level below ({user_lv} → {job_lv}). Reachable.", "Lead with strongest project outcome to close the gap."
    return -6, f"You're {abs(diff)} levels below ({user_lv} → {job_lv}).", "Aim 1-2 levels higher, or apply with a strong referral."

def _job_seniority_from_title(title):
    t = (title or "").lower()
    if "principal" in t: return "principal"
    if "staff" in t: return "staff"
    if "lead" in t or "head of" in t: return "lead"
    if "senior" in t or "sr." in t: return "senior"
    if "junior" in t or "jr." in t or "entry" in t: return "junior"
    if "intern" in t or "graduate" in t: return "intern"
    return "mid"

def _sig_resume_strength(profile, resume):
    if not resume:
        return -3, "No resume uploaded — recruiters can't assess you.", "Upload your resume in /app/resume"
    text = ""
    if isinstance(resume, dict): text = resume.get("raw_text") or resume.get("text") or ""
    else: text = getattr(resume, "raw_text", "") or getattr(resume, "text", "") or ""
    if not text: return -2, "Resume exists but has no readable text.", "Re-upload your resume as a PDF or DOCX."
    text_l = text.lower()
    # Quantification heuristic: count digits-per-bullet
    bullets = [l for l in text.split("\n") if len(l.strip()) > 30]
    quantified = sum(1 for b in bullets if any(c.isdigit() for c in b))
    q_pct = quantified / max(1, len(bullets))
    if q_pct >= 0.4: return 8, f"{int(q_pct*100)}% of bullets have numbers. Strong.", None
    if q_pct >= 0.2: return 3, f"{int(q_pct*100)}% of bullets have numbers.", "Add numbers to 3 more bullets (%, $, time saved)."
    return -2, "Very few quantified bullets — HR screens filter these out.", "Rewrite top 5 bullets: action verb + number + outcome."

def _sig_education(job, resume):
    text = ((job.description_text or "")[:3000]).lower()
    needs_degree = any(k in text for k in ["bachelor", "b.sc", "bsc", "degree required", "ba/bs", "master", "mba"])
    if not needs_degree: return 4, "No formal degree requirement mentioned.", None
    have_degree = False
    if resume:
        rtext = (resume.get("raw_text","") if isinstance(resume, dict) else getattr(resume,"raw_text","") or "").lower()
        have_degree = any(k in rtext for k in ["bachelor", "b.sc", "bsc", "master", "mba", "phd", "university", "college"])
    if have_degree: return 4, "Degree requirement met.", None
    return -3, "Degree listed as required; not visible on resume.", "Add education section, or apply to 'equivalent experience' roles."

def _sig_timing(job):
    d = _days_since(getattr(job, "posted_at", None))
    if d is None: return 2, "Posting date unknown.", None
    if d <= 2: return 5, f"Posted {int(d)}d ago — fresh window.", None
    if d <= 5: return 3, f"Posted {int(d)}d ago — still warm.", None
    if d <= 14: return 0, f"Posted {int(d)}d ago — cooling.", "Apply today; don't wait."
    if d <= 30: return -3, f"Posted {int(d)}d ago — most callbacks already gone.", "Reach out to hiring manager directly to reopen."
    return -6, f"Posted {int(d)}d ago — likely filled or stale.", "Look for a newer posting; check if role re-listed."

def _sig_competition(job):
    name = ""
    try: name = (job.company.name if job.company else "") or ""
    except Exception: pass
    n = name.lower().strip()
    if n in TIER_1: return -10, f"{name}: Tier-1 company, high applicant volume.", None
    if n in TIER_2: return -4, f"{name}: competitive mid-tier.", None
    return 3, f"{name or 'Company'}: less applicant crowding.", None

def _sig_location(job, profile):
    if getattr(job, "remote", False): return 4, "Remote role.", None
    if not profile or not profile.location: return 2, "Location unknown — set yours in profile.", "Add your location in Settings."
    jl = (job.location or "").lower(); ul = (profile.location or "").lower()
    if ul and jl and (ul.split(",")[0] in jl or jl.split(",")[0] in ul):
        return 5, f"Location match ({profile.location}).", None
    regions = getattr(profile, "regions", None) or []
    if regions:
        for r in regions:
            if r.lower() in jl: return 4, f"Region match ({r}).", None
    return -2, f"Job in {job.location or 'unknown'}, you're in {profile.location}.", "Confirm you're open to relocation, or filter for remote/your-region roles."


# ---- odds computation ----

def compute_odds(job, profile, resume=None):
    family = _job_family(job)
    signals = [
        ("skill_coverage",     _sig_skill_coverage(job, profile, resume, family)),
        ("years_experience",   _sig_years_experience(job, profile)),
        ("seniority_match",    _sig_seniority(job, profile)),
        ("resume_strength",    _sig_resume_strength(profile, resume)),
        ("education_match",    _sig_education(job, resume)),
        ("apply_timing",       _sig_timing(job)),
        ("competition",        _sig_competition(job)),
        ("location_fit",       _sig_location(job, profile)),
    ]

    # Positive contributions sum up; negatives subtract. Cap total 0-92.
    pos = sum(c for _, (c, _, _) in signals if c > 0)
    neg = sum(c for _, (c, _, _) in signals if c < 0)
    raw = pos + neg
    # Normalize: pos can reach ~70 for perfect; neg up to ~30.
    # Map raw [0, 70] -> [0, 92]
    odds = max(0, min(92, int(round(raw * 1.3))))

    why = []
    for name, (c, reason, _) in signals:
        why.append({"signal": name, "contribution": c, "reason": reason})
    why.sort(key=lambda x: abs(x["contribution"]), reverse=True)

    boosters = []
    for name, (c, reason, fix) in signals:
        if not fix: continue
        lift = 0
        if name == "skill_coverage": lift = 7
        elif name == "resume_strength": lift = 5
        elif name == "apply_timing": lift = 6
        elif name == "years_experience": lift = 2
        elif name == "education_match": lift = 3
        elif name == "seniority_match": lift = 3
        elif name == "location_fit": lift = 2
        if lift > 0:
            boosters.append({"action": fix, "lift_pct": lift, "why": reason, "signal": name})
    boosters.sort(key=lambda x: x["lift_pct"], reverse=True)

    plan = _free_plan(boosters, job, profile)

    return {
        "odds_pct": odds,
        "family": family,
        "family_display": family_display(family),
        "why": why,
        "boosters": boosters[:5],
        "free_plan": plan,
        "outreach_script": _outreach(job, profile),
    }


def _free_plan(boosters, job, profile):
    """7-day plan generated from the top boosters."""
    name = "there"
    company = job.company.name if getattr(job, "company", None) else "the team"
    title = job.title or "the role"
    base = [
        {"day": 1, "task": "Rewrite your top 3 resume bullets: action verb + number + outcome."},
        {"day": 2, "task": f"Apply to {title} at {company} today — timing boosts callback odds."},
    ]
    # Inject specific tasks from boosters (up to 3 more)
    day = 3
    for b in boosters[:3]:
        if "skill" in b["signal"] or "add a project" in b["action"].lower():
            base.append({"day": day, "task": f"Ship one small project or write one bullet showing: {b['action'].replace('Add a project or bullet showing ', '')}."}); day += 1
        elif "reach out" in b["action"].lower() or "message" in b["action"].lower():
            base.append({"day": day, "task": "Message the hiring manager on LinkedIn (script below)."}); day += 1
        elif "rewrite" in b["action"].lower() or "resume" in b["action"].lower():
            base.append({"day": day, "task": "Upload your updated resume and re-tailor it for this specific job."}); day += 1
        elif "education" in b["signal"]:
            base.append({"day": day, "task": "Add education section or mention equivalent experience in your summary."}); day += 1
    base.append({"day": max(day, 5), "task": "Follow up with the recruiter — polite 3-line email asking about next steps."})
    base.append({"day": max(day+1, 6), "task": "Apply to 2 similar roles with this same tailored resume."})
    base.append({"day": max(day+2, 7), "task": "Review your pipeline; refresh your top 5 targets for next week."})
    return base


def _outreach(job, profile):
    first = "there"
    company = job.company.name if getattr(job, "company", None) else "your team"
    title = job.title or "the role"
    headline = (profile.headline if profile and profile.headline else "an experienced professional")
    return (
        f"Hi, I'm {first} — {headline}. I saw the {title} role at {company} and it lines up "
        f"closely with what I've been doing. I've attached a short note about how I'd approach "
        f"the first 90 days. Would love 10 minutes to hear what success looks like for this role."
    )
