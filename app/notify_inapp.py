from datetime import datetime, timezone
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session
from app.db.models import Notification


def create_notification(db: Session, user_id, kind: str, title: str, body: str | None = None, link: str | None = None) -> Notification:
    n = Notification(user_id=user_id, kind=kind, title=title[:200], body=(body or "")[:800] or None, link=link)
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def list_notifications(db: Session, user_id, limit: int = 100) -> list[dict]:
    rows = db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(desc(Notification.created_at))
        .limit(limit)
    ).scalars().all()
    return [{
        "id": str(n.id),
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "read": n.read_at is not None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    } for n in rows]


def unread_count(db: Session, user_id) -> int:
    return db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
    ).scalar() or 0


def mark_all_read(db: Session, user_id):
    rows = db.execute(
        select(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for n in rows:
        n.read_at = now
    db.commit()
