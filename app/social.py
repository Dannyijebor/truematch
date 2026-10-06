from sqlalchemy import select, desc, func, or_
from sqlalchemy.orm import Session
from app.db.models import User, Profile, Follow, Post, PostLike


def get_profile(db: Session, user_id) -> Profile | None:
    return db.get(Profile, user_id)


def display_name(user: User, profile: Profile | None) -> str:
    if user.full_name:
        return user.full_name
    if profile and profile.username:
        return "@" + profile.username
    return user.email.split("@")[0]


def is_following(db: Session, follower_id, following_id) -> bool:
    r = db.get(Follow, (follower_id, following_id))
    return r is not None


def follow(db: Session, follower_id, following_id) -> bool:
    if follower_id == following_id:
        return False
    if db.get(Follow, (follower_id, following_id)):
        return False
    db.add(Follow(follower_id=follower_id, following_id=following_id))
    db.commit()
    return True


def unfollow(db: Session, follower_id, following_id) -> bool:
    r = db.get(Follow, (follower_id, following_id))
    if not r:
        return False
    db.delete(r)
    db.commit()
    return True


def followers_count(db: Session, user_id) -> int:
    return db.execute(select(func.count()).select_from(Follow).where(Follow.following_id == user_id)).scalar() or 0


def following_count(db: Session, user_id) -> int:
    return db.execute(select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)).scalar() or 0


def create_post(db: Session, user_id, body: str, image_url=None, link_url=None) -> Post:
    body = (body or "").strip()
    if not body or len(body) > 3000:
        raise ValueError("post body must be 1-3000 chars")
    post = Post(user_id=user_id, body=body, image_url=image_url, link_url=link_url)
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def feed_for(db: Session, user_id, limit: int = 40) -> list[dict]:
    following_ids = [r.following_id for r in db.execute(select(Follow).where(Follow.follower_id == user_id)).scalars()]
    visible = [user_id] + following_ids

    stmt = (
        select(Post)
        .where(Post.user_id.in_(visible))
        .order_by(desc(Post.created_at))
        .limit(limit)
    )
    posts = db.execute(stmt).scalars().all()

    return [_serialize_post(db, p, user_id) for p in posts]


def discover_feed(db: Session, user_id, limit: int = 40) -> list[dict]:
    stmt = select(Post).order_by(desc(Post.created_at)).limit(limit)
    posts = db.execute(stmt).scalars().all()
    return [_serialize_post(db, p, user_id) for p in posts]


def _serialize_post(db: Session, p: Post, viewer_id) -> dict:
    author = db.get(User, p.user_id)
    profile = db.get(Profile, p.user_id)
    liked = db.get(PostLike, (viewer_id, p.id)) is not None
    return {
        "id": str(p.id),
        "body": p.body,
        "image_url": p.image_url,
        "link_url": p.link_url,
        "likes": p.likes_count,
        "liked": liked,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "author": {
            "user_id": str(author.id),
            "name": display_name(author, profile),
            "username": profile.username if profile else None,
            "title": profile.title if profile else None,
            "company": profile.company_name if profile else None,
            "avatar_url": profile.avatar_url if profile else None,
        },
    }


def toggle_like(db: Session, user_id, post_id) -> dict:
    p = db.get(Post, post_id)
    if not p:
        return {"ok": False, "error": "no post"}
    existing = db.get(PostLike, (user_id, post_id))
    if existing:
        db.delete(existing)
        p.likes_count = max(0, (p.likes_count or 0) - 1)
        liked = False
    else:
        db.add(PostLike(user_id=user_id, post_id=post_id))
        p.likes_count = (p.likes_count or 0) + 1
        liked = True
    db.commit()
    return {"ok": True, "likes": p.likes_count, "liked": liked}


def search_people(db: Session, q: str, limit: int = 30) -> list[dict]:
    like = f"%{(q or '').strip().lower()}%"
    stmt = (
        select(User, Profile)
        .join(Profile, Profile.user_id == User.id, isouter=True)
        .where(
            or_(
                func.lower(func.coalesce(Profile.username, "")).like(like),
                func.lower(func.coalesce(User.full_name, "")).like(like),
                func.lower(func.coalesce(Profile.headline, "")).like(like),
                func.lower(func.coalesce(Profile.title, "")).like(like),
            )
        )
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    out = []
    for user, profile in rows:
        out.append({
            "user_id": str(user.id),
            "name": display_name(user, profile),
            "username": profile.username if profile else None,
            "title": profile.title if profile else None,
            "company": profile.company_name if profile else None,
            "avatar_url": profile.avatar_url if profile else None,
            "bio": profile.bio if profile else None,
        })
    return out


# ---------- direct messages ----------
from app.db.models import DirectMessage


def send_message(db: Session, from_id, to_id, body: str = "", kind: str = "text",
                 media_url: str | None = None, media_duration: float | None = None,
                 reply_to_id=None) -> DirectMessage:
    body = (body or "").strip()
    if kind not in ("text", "image", "voice", "sticker"):
        kind = "text"
    if kind == "text" and (not body or len(body) > 4000):
        raise ValueError("message must be 1-4000 chars")
    if kind in ("image", "voice", "sticker") and not media_url:
        raise ValueError("media required")
    if from_id == to_id:
        raise ValueError("cannot message yourself")

    msg = DirectMessage(
        from_user_id=from_id, to_user_id=to_id,
        body=body[:4000] if body else "",
        kind=kind, media_url=media_url,
        media_duration=media_duration,
        reply_to_id=reply_to_id,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def delete_message_for_me(db: Session, user_id, message_id):
    m = db.get(DirectMessage, message_id)
    if not m:
        raise ValueError("not found")
    if m.from_user_id == user_id:
        m.deleted_for_sender = True
    else:
        db.delete(m)
    db.commit()


def toggle_sticker(db: Session, user_id, name: str, kind: str, data: str) -> dict:
    existing = db.execute(
        select(Sticker).where(Sticker.user_id == user_id, Sticker.name == name)
    ).scalar_one_or_none()
    if existing:
        existing.kind = kind
        existing.data = data
        db.commit()
        return {"id": str(existing.id), "name": name, "kind": kind, "data": data, "saved": True}
    s = Sticker(user_id=user_id, name=name[:60], kind=kind, data=data)
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": str(s.id), "name": s.name, "kind": s.kind, "data": s.data, "saved": True}


def list_stickers(db: Session, user_id) -> list[dict]:
    rows = db.execute(
        select(Sticker).where(Sticker.user_id == user_id).order_by(desc(Sticker.created_at)).limit(120)
    ).scalars().all()
    return [{"id": str(s.id), "name": s.name, "kind": s.kind, "data": s.data} for s in rows]


def delete_sticker(db: Session, user_id, sticker_id):
    s = db.get(Sticker, sticker_id)
    if not s or s.user_id != user_id:
        raise ValueError("not found")
    db.delete(s)
    db.commit()


def inbox(db: Session, user_id) -> list[dict]:
    """Return list of conversations, most recent first, with unread counts."""
    # All users we've exchanged messages with
    q1 = db.execute(
        select(DirectMessage.to_user_id).where(DirectMessage.from_user_id == user_id)
    ).scalars().all()
    q2 = db.execute(
        select(DirectMessage.from_user_id).where(DirectMessage.to_user_id == user_id)
    ).scalars().all()
    others = set(q1) | set(q2)

    out = []
    for other_id in others:
        # Last message between the two
        last = db.execute(
            select(DirectMessage)
            .where(
                or_(
                    (DirectMessage.from_user_id == user_id) & (DirectMessage.to_user_id == other_id),
                    (DirectMessage.from_user_id == other_id) & (DirectMessage.to_user_id == user_id),
                )
            )
            .order_by(desc(DirectMessage.created_at))
            .limit(1)
        ).scalar_one_or_none()

        unread = db.execute(
            select(func.count()).select_from(DirectMessage).where(
                DirectMessage.from_user_id == other_id,
                DirectMessage.to_user_id == user_id,
                DirectMessage.read_at.is_(None),
            )
        ).scalar() or 0

        other_user = db.get(User, other_id)
        other_profile = db.get(Profile, other_id)
        out.append({
            "other_user_id": str(other_id),
            "name": display_name(other_user, other_profile),
            "username": other_profile.username if other_profile else None,
            "title": other_profile.title if other_profile else None,
            "company": other_profile.company_name if other_profile else None,
            "avatar_url": other_profile.avatar_url if other_profile else None,
            "last_body": (last.body[:80] + "…") if last and len(last.body) > 80 else (last.body if last else ""),
            "last_at": last.created_at.isoformat() if last else None,
            "last_from_me": (last.from_user_id == user_id) if last else False,
            "unread": unread,
        })

    out.sort(key=lambda r: r["last_at"] or "", reverse=True)
    return out


def thread(db: Session, user_id, other_id, limit: int = 200) -> list[dict]:
    """Return messages between user_id and other_id, mark incoming as read."""
    rows = db.execute(
        select(DirectMessage)
        .where(
            or_(
                (DirectMessage.from_user_id == user_id) & (DirectMessage.to_user_id == other_id),
                (DirectMessage.from_user_id == other_id) & (DirectMessage.to_user_id == user_id),
            )
        )
        .order_by(DirectMessage.created_at)
        .limit(limit)
    ).scalars().all()

    # Mark incoming as delivered AND read (opening the thread = seen)
    now_dirty = False
    for m in rows:
        if m.to_user_id == user_id:
            if m.delivered_at is None:
                m.delivered_at = func.now()
                now_dirty = True
            if m.read_at is None:
                m.read_at = func.now()
                now_dirty = True
    if now_dirty:
        db.commit()

    out = []
    for m in rows:
        if m.deleted_for_sender and m.from_user_id == user_id:
            continue
        reply = None
        if m.reply_to_id:
            parent = db.get(DirectMessage, m.reply_to_id)
            if parent:
                preview = parent.body[:80] if parent.body else ("[image]" if parent.kind == "image" else "[voice]" if parent.kind == "voice" else "[sticker]")
                reply = {
                    "id": str(parent.id),
                    "preview": preview,
                    "from_me": parent.from_user_id == user_id,
                }
        out.append({
            "id": str(m.id),
            "body": m.body,
            "kind": m.kind or "text",
            "media_url": m.media_url,
            "media_duration": m.media_duration,
            "from_me": m.from_user_id == user_id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "read": m.read_at is not None,
                "delivered": m.delivered_at is not None,
            "reply": reply,
        })
    return out


def unread_messages_count(db: Session, user_id) -> int:
    return db.execute(
        select(func.count()).select_from(DirectMessage).where(
            DirectMessage.to_user_id == user_id,
            DirectMessage.read_at.is_(None),
        )
    ).scalar() or 0


def update_post(db: Session, user_id, post_id, new_body: str) -> Post:
    p = db.get(Post, post_id)
    if not p or p.user_id != user_id:
        raise ValueError("not found or not yours")
    body = (new_body or "").strip()
    if not body or len(body) > 3000:
        raise ValueError("body must be 1-3000 chars")
    p.body = body
    db.commit()
    db.refresh(p)
    return p


def delete_post(db: Session, user_id, post_id):
    p = db.get(Post, post_id)
    if not p or p.user_id != user_id:
        raise ValueError("not found or not yours")
    db.delete(p)
    db.commit()
