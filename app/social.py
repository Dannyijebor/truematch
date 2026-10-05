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
