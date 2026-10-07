import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, or_, and_, desc
from sqlalchemy.orm import Session
from app.db.models import Call, DirectMessage, Profile, User


# ---------- messages polling ----------

def messages_since(db: Session, user_id, other_id, since_iso: str | None) -> list[dict]:
    q = select(DirectMessage).where(
        or_(
            and_(DirectMessage.from_user_id == user_id, DirectMessage.to_user_id == other_id),
            and_(DirectMessage.from_user_id == other_id, DirectMessage.to_user_id == user_id),
        )
    )
    if since_iso:
        try:
            dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
            q = q.where(DirectMessage.created_at > dt)
        except Exception:
            pass
    q = q.order_by(DirectMessage.created_at).limit(200)
    rows = db.execute(q).scalars().all()

    # mark incoming as delivered (NOT read — read happens only when thread is opened)
    dirty = False
    for m in rows:
        if m.to_user_id == user_id and m.delivered_at is None:
            m.delivered_at = datetime.now(timezone.utc)
            dirty = True
    if dirty:
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
                reply = {"id": str(parent.id), "preview": preview,
                         "from_me": parent.from_user_id == user_id}
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


def unread_from(db: Session, user_id, other_id) -> int:
    from sqlalchemy import func
    return db.execute(
        select(func.count()).select_from(DirectMessage).where(
            DirectMessage.from_user_id == other_id,
            DirectMessage.to_user_id == user_id,
            DirectMessage.read_at.is_(None),
        )
    ).scalar() or 0


# ---------- calls (WebRTC signaling) ----------

CALL_TTL_MINUTES = 2


def start_call(db: Session, caller: User, callee_id, kind: str) -> Call:
    if caller.id == callee_id:
        raise ValueError("You can't call yourself — open a chat with the other person to test.")
    if kind not in ("audio", "video"):
        raise ValueError("Invalid call type.")
    callee = db.get(User, callee_id)
    if not callee:
        raise ValueError("This person is no longer available.")

    # End any stale ringing calls between these two
    stale = db.execute(
        select(Call).where(
            Call.status == "ringing",
            or_(
                and_(Call.caller_id == caller.id, Call.callee_id == callee_id),
                and_(Call.caller_id == callee_id, Call.callee_id == caller.id),
            )
        )
    ).scalars().all()
    for c in stale:
        c.status = "ended"
        c.ended_at = datetime.now(timezone.utc)

    call = Call(caller_id=caller.id, callee_id=callee_id, kind=kind, status="ringing")
    db.add(call)
    db.commit()
    db.refresh(call)
    return call


def get_call(db: Session, call_id) -> Call | None:
    return db.get(Call, call_id)


def active_incoming(db: Session, user_id) -> dict | None:
    """Any call ringing for me right now, from anyone."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CALL_TTL_MINUTES)
    call = db.execute(
        select(Call).where(
            Call.callee_id == user_id,
            Call.status == "ringing",
            Call.created_at > cutoff,
        ).order_by(desc(Call.created_at)).limit(1)
    ).scalar_one_or_none()
    if not call:
        return None
    caller = db.get(User, call.caller_id)
    profile = db.get(Profile, call.caller_id)
    from app.social import display_name
    return {
        "call_id": str(call.id),
        "kind": call.kind,
        "from": {
            "user_id": str(caller.id),
            "name": display_name(caller, profile),
            "avatar_url": profile.avatar_url if profile else None,
        }
    }


def accept_call(db: Session, call_id, user_id) -> Call:
    c = db.get(Call, call_id)
    if not c or c.callee_id != user_id:
        raise ValueError("not yours")
    if c.status != "ringing":
        raise ValueError(f"call is {c.status}")
    c.status = "accepted"
    db.commit()
    db.refresh(c)
    return c


def decline_call(db: Session, call_id, user_id) -> Call:
    c = db.get(Call, call_id)
    if not c or user_id not in (c.caller_id, c.callee_id):
        raise ValueError("not yours")
    c.status = "declined"
    c.ended_at = datetime.now(timezone.utc)
    db.commit()
    return c


def end_call(db: Session, call_id, user_id) -> Call:
    c = db.get(Call, call_id)
    if not c or user_id not in (c.caller_id, c.callee_id):
        raise ValueError("not yours")
    c.status = "ended"
    c.ended_at = datetime.now(timezone.utc)
    db.commit()
    return c


def set_offer(db: Session, call_id, user_id, offer: dict) -> Call:
    c = db.get(Call, call_id)
    if not c or c.caller_id != user_id:
        raise ValueError("not your offer")
    c.offer = offer
    db.commit()
    return c


def set_answer(db: Session, call_id, user_id, answer: dict) -> Call:
    c = db.get(Call, call_id)
    if not c or c.callee_id != user_id:
        raise ValueError("not your answer")
    c.answer = answer
    db.commit()
    return c


def add_ice(db: Session, call_id, user_id, candidate: dict, side: str) -> Call:
    c = db.get(Call, call_id)
    if not c:
        raise ValueError("no call")
    if side == "caller" and c.caller_id != user_id:
        raise ValueError("not caller")
    if side == "callee" and c.callee_id != user_id:
        raise ValueError("not callee")
    if side == "caller":
        c.ice_caller = (c.ice_caller or []) + [candidate]
    else:
        c.ice_callee = (c.ice_callee or []) + [candidate]
    db.commit()
    return c


def set_reaction(db: Session, call_id, user_id, emoji: str) -> Call:
    c = db.get(Call, call_id)
    if not c or user_id not in (c.caller_id, c.callee_id):
        raise ValueError("not yours")
    c.reaction = {
        "emoji": emoji[:8],
        "at": datetime.now(timezone.utc).isoformat(),
        "from": str(user_id),
    }
    db.commit()
    return c
