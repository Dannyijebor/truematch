"""Stories — ephemeral 24h updates."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from app.db.models import Story, User, Profile, Follow


BACKGROUNDS = {
    "aurora":   "linear-gradient(135deg, #10b981 0%, #06b6d4 50%, #3b82f6 100%)",
    "ember":    "linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)",
    "midnight": "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)",
    "berry":    "linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)",
    "forest":   "linear-gradient(135deg, #059669 0%, #065f46 100%)",
    "sunset":   "linear-gradient(135deg, #f97316 0%, #ec4899 100%)",
    "royal":    "linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #ec4899 100%)",
    "graphite": "linear-gradient(135deg, #334155 0%, #0f172a 100%)",
}


def create_story(db: Session, user_id, kind: str, body: str | None = None,
                 image_url: str | None = None, background: str = "aurora") -> Story:
    if kind not in ("text", "image"):
        kind = "text"
    if background not in BACKGROUNDS:
        background = "aurora"

    body = (body or "").strip()[:280] or None
    if kind == "text" and not body:
        raise ValueError("text required for text stories")
    if kind == "image" and not image_url:
        raise ValueError("image required for image stories")

    now = datetime.now(timezone.utc)
    story = Story(
        user_id=user_id,
        kind=kind,
        body=body,
        image_url=image_url,
        background=background,
        seen_by=[],
        expires_at=now + timedelta(hours=24),
    )
    db.add(story)
    db.commit()
    db.refresh(story)
    return story


def my_active_stories(db: Session, user_id) -> list[Story]:
    now = datetime.now(timezone.utc)
    return db.execute(
        select(Story).where(
            Story.user_id == user_id,
            Story.expires_at > now,
        ).order_by(Story.created_at)
    ).scalars().all()


def delete_story(db: Session, user_id, story_id):
    s = db.get(Story, story_id)
    if not s or s.user_id != user_id:
        raise ValueError("not found")
    db.delete(s)
    db.commit()


def story_groups(db: Session, viewer_id) -> list[dict]:
    """Return groups: [{'user': {...}, 'stories': [...], 'has_unseen': bool, 'is_me': bool}]"""
    now = datetime.now(timezone.utc)

    # who do we follow
    following = [r.following_id for r in db.execute(
        select(Follow).where(Follow.follower_id == viewer_id)
    ).scalars()]
    visible_user_ids = set(following) | {viewer_id}

    rows = db.execute(
        select(Story).where(
            Story.user_id.in_(visible_user_ids),
            Story.expires_at > now,
        ).order_by(Story.created_at)
    ).scalars().all()

    by_user: dict = {}
    for s in rows:
        by_user.setdefault(s.user_id, []).append(s)

    groups = []
    me_group = None
    for uid, stories in by_user.items():
        u = db.get(User, uid)
        p = db.get(Profile, uid)
        if not u:
            continue
        from app.social import display_name
        has_unseen = any(viewer_id not in (s.seen_by or []) and uid != viewer_id for s in stories)
        group = {
            "user_id": str(uid),
            "name": display_name(u, p),
            "avatar_url": p.avatar_url if p else None,
            "is_me": uid == viewer_id,
            "has_unseen": has_unseen,
            "stories": [_serialize(s, viewer_id) for s in stories],
        }
        if uid == viewer_id:
            me_group = group
        else:
            groups.append(group)

    # sort: unseen first, then by most recent
    groups.sort(key=lambda g: (not g["has_unseen"], g["stories"][-1]["created_at"]), reverse=False)
    groups.sort(key=lambda g: (g["has_unseen"], g["stories"][-1]["created_at"]), reverse=True)

    # my group always first
    out = []
    if me_group:
        out.append(me_group)
    out.extend(groups)
    return out


def _serialize(s: Story, viewer_id) -> dict:
    return {
        "id": str(s.id),
        "kind": s.kind,
        "body": s.body,
        "image_url": s.image_url,
        "background": s.background,
        "background_css": BACKGROUNDS.get(s.background, BACKGROUNDS["aurora"]),
        "seen": viewer_id in (s.seen_by or []),
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "ago": _ago(s.created_at),
    }


def _ago(dt) -> str:
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = (now - dt).total_seconds()
    if diff < 60: return "just now"
    if diff < 3600: return f"{int(diff/60)}m ago"
    if diff < 86400: return f"{int(diff/3600)}h ago"
    return f"{int(diff/86400)}d ago"


def mark_seen(db: Session, viewer_id, story_id):
    s = db.get(Story, story_id)
    if not s:
        return
    seen = list(s.seen_by or [])
    if viewer_id not in seen:
        seen.append(str(viewer_id))
        s.seen_by = seen
        db.commit()


def cleanup_expired(db: Session) -> int:
    now = datetime.now(timezone.utc)
    rows = db.execute(select(Story).where(Story.expires_at <= now)).scalars().all()
    n = 0
    for s in rows:
        db.delete(s)
        n += 1
    db.commit()
    return n
