"""
Portfolio builder — data operations.
"""
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session
from app.db.models import Profile, PortfolioItem, User


THEMES = ("editorial", "minimal", "executive", "chronicle")
KINDS = ("project", "experience", "education", "certification", "link")
ACCENTS = ["#10b981", "#3b82f6", "#8b5cf6", "#f59e0b", "#ef4444", "#ec4899", "#14b8a6", "#a16207"]


# ---------- settings ----------

def get_portfolio_settings(db: Session, user_id) -> dict:
    p = db.get(Profile, user_id)
    if not p:
        p = Profile(user_id=user_id)
        db.add(p); db.commit(); db.refresh(p)
    return {
        "theme": p.portfolio_theme or "editorial",
        "tagline": p.portfolio_tagline,
        "about": p.portfolio_about,
        "hero_image": p.portfolio_hero_image,
        "accent": p.portfolio_accent or "#10b981",
        "is_public": bool(p.portfolio_is_public),
        "has_vercel_token": bool(p.vercel_token),
    }


def save_portfolio_settings(db: Session, user_id, data: dict):
    p = db.get(Profile, user_id) or Profile(user_id=user_id)

    theme = (data.get("theme") or "editorial").lower()
    if theme not in THEMES:
        theme = "editorial"
    p.portfolio_theme = theme

    accent = (data.get("accent") or "#10b981").strip()
    if not accent.startswith("#") or len(accent) != 7:
        accent = "#10b981"
    p.portfolio_accent = accent

    p.portfolio_tagline = (data.get("tagline") or "").strip()[:200] or None
    p.portfolio_about = (data.get("about") or "").strip()[:3000] or None
    p.portfolio_is_public = bool(data.get("is_public", True))

    if "hero_image" in data:
        p.portfolio_hero_image = data["hero_image"] or None

    if "vercel_token" in data:
        tok = (data.get("vercel_token") or "").strip()
        p.vercel_token = tok or None

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
