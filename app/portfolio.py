"""
Portfolio builder - data operations.
"""
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session
from app.db.models import Profile, PortfolioItem, User


THEMES = ("editorial", "minimal", "executive", "chronicle")
KINDS = ("project", "experience", "education", "certification", "link")

# 12 named color presets. Value = (main, glow, soft)
COLORS = {
    "rose":     ("#e11d48", "#e11d4855", "#e11d4822"),
    "crimson":  ("#dc2626", "#dc262655", "#dc262622"),
    "violet":   ("#7c3aed", "#7c3aed55", "#7c3aed22"),
    "royal":    ("#1e40af", "#1e40af55", "#1e40af22"),
    "sapphire": ("#0284c7", "#0284c755", "#0284c722"),
    "emerald":  ("#00a884", "#00a88455", "#00a88422"),
    "amber":    ("#d97706", "#d9770655", "#d9770622"),
    "sunset":   ("#ea580c", "#ea580c55", "#ea580c22"),
    "midnight": ("#0f172a", "#0f172a55", "#0f172a22"),
    "onyx":     ("#1f1f1f", "#1f1f1f55", "#1f1f1f22"),
    "ivory":    ("#a8a29e", "#a8a29e55", "#a8a29e22"),
    "forest":   ("#15803d", "#15803d55", "#15803d22"),
}

SCENES = (
    "aurora", "butterfly", "snow", "night", "field",
    "cherry", "ocean", "forest", "desert", "rain",
)


# Personality presets — one-tap bundles
PRESETS = {
    "minimalist": {"color": "ivory",    "scene": "aurora",  "font": "system",  "hero": "centered"},
    "bold":       {"color": "crimson",  "scene": "rain",    "font": "display", "hero": "left"},
    "dreamy":     {"color": "violet",   "scene": "butterfly","font": "serif",   "hero": "centered"},
    "executive":  {"color": "midnight", "scene": "aurora",  "font": "system",  "hero": "split"},
    "editorial":  {"color": "onyx",     "scene": "ocean",   "font": "serif",   "hero": "left"},
    "playful":    {"color": "amber",    "scene": "field",   "font": "display", "hero": "centered"},
    "serene":     {"color": "sapphire", "scene": "ocean",   "font": "system",  "hero": "centered"},
    "nocturnal":  {"color": "midnight", "scene": "night",   "font": "display", "hero": "split"},
}

FONTS = {
    "system":  "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
    "serif":   "'Georgia', 'Times New Roman', serif",
    "display": "'Inter Tight', -apple-system, BlinkMacSystemFont, system-ui, sans-serif",
}

HERO_LAYOUTS = ("centered", "split", "left")

SECTION_KEYS = ("about", "projects", "experience", "education", "certifications", "skills", "links")

DEFAULT_ACCENT_KEY = "emerald"
DEFAULT_SCENE = "aurora"


def resolve_accent(key: str | None) -> tuple[str, str, str]:
    """Return (main, glow, soft) for a preset key. Falls back to emerald."""
    k = (key or DEFAULT_ACCENT_KEY).lower()
    if k not in COLORS:
        k = DEFAULT_ACCENT_KEY
    return COLORS[k]


# ---------- settings ----------

def get_portfolio_settings(db: Session, user_id) -> dict:
    p = db.get(Profile, user_id)
    if not p:
        p = Profile(user_id=user_id)
        db.add(p); db.commit(); db.refresh(p)

    accent_key = getattr(p, "portfolio_accent_key", None) or DEFAULT_ACCENT_KEY
    if accent_key not in COLORS:
        accent_key = DEFAULT_ACCENT_KEY
    scene = getattr(p, "portfolio_scene", None) or DEFAULT_SCENE
    if scene not in SCENES:
        scene = DEFAULT_SCENE

    accent_main, accent_glow, accent_soft = resolve_accent(accent_key)

    cfg = p.portfolio_config or {}
    custom_accent = (cfg.get("custom_accent") or "").strip()
    if custom_accent and (custom_accent.startswith("#") and len(custom_accent) == 7):
        accent_main = custom_accent
        accent_glow = custom_accent + "55"
        accent_soft = custom_accent + "22"
    else:
        custom_accent = ""

    font = cfg.get("font") or "system"
    if font not in FONTS: font = "system"
    hero = cfg.get("hero") or "centered"
    if hero not in HERO_LAYOUTS: hero = "centered"
    personality = cfg.get("personality") or ""
    if personality and personality not in PRESETS: personality = ""

    sections = cfg.get("sections") or {}
    sections_visible = {k: bool(sections.get(k, True)) for k in SECTION_KEYS}

    return {
        "theme": p.portfolio_theme or "editorial",
        "tagline": p.portfolio_tagline,
        "about": p.portfolio_about,
        "hero_image": p.portfolio_hero_image,
        "accent_key": accent_key,
        "accent": accent_main,
        "accent_glow": accent_glow,
        "accent_soft": accent_soft,
        "custom_accent": custom_accent,
        "scene": scene,
        "font": font,
        "font_stack": FONTS[font],
        "hero": hero,
        "personality": personality,
        "sections_visible": sections_visible,
        "hidden_chips": cfg.get("hidden_chips") or [],
        "custom_chips": cfg.get("custom_chips") or [],
        "is_public": bool(p.portfolio_is_public),
        "has_vercel_token": bool(p.vercel_token),
    }


def save_portfolio_settings(db: Session, user_id, data: dict):
    p = db.get(Profile, user_id) or Profile(user_id=user_id)

    theme = (data.get("theme") or "editorial").lower()
    if theme not in THEMES:
        theme = "editorial"
    p.portfolio_theme = theme

    accent_key = (data.get("accent_key") or DEFAULT_ACCENT_KEY).lower().strip()
    if accent_key not in COLORS:
        accent_key = DEFAULT_ACCENT_KEY
    p.portfolio_accent_key = accent_key
    p.portfolio_accent = resolve_accent(accent_key)[0]

    scene = (data.get("scene") or DEFAULT_SCENE).lower().strip()
    if scene not in SCENES:
        scene = DEFAULT_SCENE
    p.portfolio_scene = scene

    p.portfolio_tagline = (data.get("tagline") or "").strip()[:200] or None
    p.portfolio_about = (data.get("about") or "").strip()[:3000] or None
    p.portfolio_is_public = bool(data.get("is_public", True))

    if "hero_image" in data:
        p.portfolio_hero_image = data["hero_image"] or None

    if "vercel_token" in data:
        tok = (data.get("vercel_token") or "").strip()
        p.vercel_token = tok or None

    # --- config JSONB: personality + custom_accent + font + hero + sections ---
    cfg = dict(p.portfolio_config or {})

    personality = (data.get("personality") or "").strip().lower()
    if personality and personality not in PRESETS: personality = ""
    cfg["personality"] = personality

    custom = (data.get("custom_accent") or "").strip()
    if custom and custom.startswith("#") and len(custom) == 7:
        cfg["custom_accent"] = custom
    else:
        cfg.pop("custom_accent", None)

    font = (data.get("font") or "system").strip().lower()
    if font not in FONTS: font = "system"
    cfg["font"] = font

    hero = (data.get("hero") or "centered").strip().lower()
    if hero not in HERO_LAYOUTS: hero = "centered"
    cfg["hero"] = hero

    sections = cfg.get("sections") or {}
    new_sections = dict(sections)
    for k in SECTION_KEYS:
        new_sections[k] = bool(data.get("sec_" + k))
    cfg["sections"] = new_sections

    p.portfolio_config = cfg

    db.add(p); db.commit()
    return p


# ---------- items ----------

def list_items(db: Session, user_id, only_visible: bool = False) -> list[dict]:
    q = select(PortfolioItem).where(PortfolioItem.user_id == user_id)
    if only_visible:
        q = q.where(PortfolioItem.visible == True)
    q = q.order_by(PortfolioItem.sort_order, desc(PortfolioItem.created_at))
    rows = db.execute(q).scalars().all()
    return [_serialize_item(i) for i in rows]


def _serialize_item(i: PortfolioItem) -> dict:
    return {
        "id": str(i.id),
        "kind": i.kind,
        "title": i.title,
        "subtitle": i.subtitle,
        "description": i.description,
        "image_url": i.image_url,
        "link_url": i.link_url,
        "tags": i.tags or [],
        "start_date": i.start_date,
        "end_date": i.end_date,
        "sort_order": i.sort_order,
        "visible": bool(i.visible),
    }


def add_item(db: Session, user_id, data: dict) -> PortfolioItem:
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("title required")

    kind = (data.get("kind") or "project").lower()
    if kind not in KINDS:
        kind = "project"

    # auto sort_order = max + 1
    max_order = db.execute(
        select(func.coalesce(func.max(PortfolioItem.sort_order), 0)).where(PortfolioItem.user_id == user_id)
    ).scalar() or 0

    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    item = PortfolioItem(
        user_id=user_id,
        kind=kind,
        title=title[:200],
        subtitle=(data.get("subtitle") or "").strip()[:200] or None,
        description=(data.get("description") or "").strip()[:3000] or None,
        image_url=data.get("image_url") or None,
        link_url=(data.get("link_url") or "").strip()[:500] or None,
        tags=tags[:10],
        start_date=(data.get("start_date") or "").strip()[:20] or None,
        end_date=(data.get("end_date") or "").strip()[:20] or None,
        sort_order=max_order + 1,
        visible=True,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


def delete_item(db: Session, user_id, item_id):
    item = db.get(PortfolioItem, item_id)
    if not item or item.user_id != user_id:
        raise ValueError("not found")
    db.delete(item); db.commit()


def toggle_item_visibility(db: Session, user_id, item_id):
    item = db.get(PortfolioItem, item_id)
    if not item or item.user_id != user_id:
        raise ValueError("not found")
    item.visible = not item.visible
    db.commit()
    return item


def move_item(db: Session, user_id, item_id, direction: str):
    item = db.get(PortfolioItem, item_id)
    if not item or item.user_id != user_id:
        raise ValueError("not found")
    if direction == "up":
        item.sort_order = max(0, (item.sort_order or 0) - 1)
    elif direction == "down":
        item.sort_order = (item.sort_order or 0) + 1
    db.commit()
    return item


# ---------- public portfolio (for /p/{username}) ----------

def public_portfolio(db: Session, username: str) -> dict | None:
    """Return a dict of everything needed to render a public portfolio.
    Returns None if the username doesn't exist or the portfolio is private."""
    from app.db.models import User

    p = db.execute(
        select(Profile).where(Profile.username == username)
    ).scalar_one_or_none()
    if not p:
        return None
    if not p.portfolio_is_public:
        return None

    u = db.get(User, p.user_id)

    items = list_items(db, p.user_id, only_visible=True)

    # Group items by kind
    projects = [i for i in items if i["kind"] == "project"]
    experience = [i for i in items if i["kind"] == "experience"]
    education = [i for i in items if i["kind"] == "education"]
    certifications = [i for i in items if i["kind"] == "certification"]
    links = [i for i in items if i["kind"] == "link"]

    settings = get_portfolio_settings(db, p.user_id)

    return {
        "portfolio_user": {
            "id": str(u.id) if u else None,
            "full_name": u.full_name if u else None,
            "email": u.email if u else None,
            "country": u.country if u else None,
        },
        "profile": {
            "username": p.username,
            "avatar_url": p.avatar_url,
            "banner_url": p.banner_url,
            "social_links": p.social_links or {},
            "title": p.title,
            "company_name": p.company_name,
            "headline": p.headline,
            "bio": p.bio,
            "location": p.location,
            "seniority": p.seniority,
            "years_experience": p.years_experience,
            "skills": p.skills or [],
            "remote_ok": bool(p.remote_ok),
        },
        "settings": settings,
        "items": {
            "projects": projects,
            "experience": experience,
            "education": education,
            "certifications": certifications,
            "links": links,
            "all": items,
        },
    }
