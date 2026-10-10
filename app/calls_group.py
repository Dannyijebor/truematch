"""Group call helpers: participants, invites, per-peer signals."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select, or_, desc
from sqlalchemy.orm import Session

from app.db.models import Call, CallParticipant, CallSignal, Profile, User
from app.db.session import get_db
from app.calls import get_call
from app.social import display_name


# ---------- helpers ----------

def _now():
    return datetime.now(timezone.utc)


def is_member(db, call_id, user_id) -> bool:
    c = db.get(Call, call_id)
    if not c:
        return False
    if user_id in (c.caller_id, c.callee_id):
        return True
    row = db.execute(
        select(CallParticipant).where(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == user_id,
            CallParticipant.status.in_(["invited", "joined"]),
        )
    ).scalar_one_or_none()
    return row is not None


def add_participant(db, call_id, invited_by, user_id) -> CallParticipant:
    """Invite someone to a call. Idempotent."""
    if not is_member(db, call_id, invited_by):
        raise ValueError("you are not in this call")
    target = db.get(User, user_id)
    if not target:
        raise ValueError("user not found")
    existing = db.execute(
        select(CallParticipant).where(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == user_id,
        )
    ).scalar_one_or_none()
    if existing:
        if existing.status == "left":
            existing.status = "invited"
            existing.left_at = None
            db.commit()
        return existing
    p = CallParticipant(
        call_id=call_id, user_id=user_id,
        status="invited", invited_by=invited_by,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    # notify the invitee via a signal
    push_signal(db, call_id, invited_by, user_id, "invite", {})
    return p


def join_call(db, call_id, user_id) -> CallParticipant:
    p = db.execute(
        select(CallParticipant).where(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not p:
        raise ValueError("no invite for you")
    p.status = "joined"
    p.joined_at = _now()
    p.left_at = None
    db.commit()
    db.refresh(p)
    return p


def leave_call(db, call_id, user_id) -> CallParticipant:
    p = db.execute(
        select(CallParticipant).where(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not p:
        raise ValueError("not a participant")
    p.status = "left"
    p.left_at = _now()
    db.commit()
    db.refresh(p)
    return p


def list_participants(db, call_id) -> list[dict]:
    c = db.get(Call, call_id)
    if not c:
        return []
    out = []
    for uid, role in [(c.caller_id, "caller"), (c.callee_id, "callee")]:
        if not uid:
            continue
        u = db.get(User, uid)
        pr = db.get(Profile, uid)
        out.append({
            "user_id": str(uid),
            "name": display_name(u, pr) if u else "Unknown",
            "avatar_url": pr.avatar_url if pr else None,
            "role": role,
            "status": "joined",
        })
    rows = db.execute(
        select(CallParticipant).where(
            CallParticipant.call_id == call_id,
            CallParticipant.status.in_(["invited", "joined"]),
        ).order_by(CallParticipant.created_at)
    ).scalars().all()
    for p in rows:
        u = db.get(User, p.user_id)
        pr = db.get(Profile, p.user_id)
        out.append({
            "user_id": str(p.user_id),
            "name": display_name(u, pr) if u else "Unknown",
            "avatar_url": pr.avatar_url if pr else None,
            "role": "guest",
            "status": p.status,
        })
    return out


def push_signal(db, call_id, from_user_id, to_user_id, kind, payload: dict) -> CallSignal:
    s = CallSignal(
        call_id=call_id, from_user_id=from_user_id,
        to_user_id=to_user_id, kind=kind, payload=payload or {},
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def signals_for_me(db, call_id, user_id, since_iso: str | None) -> list[dict]:
    q = select(CallSignal).where(
        CallSignal.call_id == call_id,
        CallSignal.to_user_id == user_id,
    )
    if since_iso:
        try:
            dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
            q = q.where(CallSignal.created_at > dt)
        except Exception:
            pass
    q = q.order_by(CallSignal.created_at).limit(200)
    rows = db.execute(q).scalars().all()
    return [{
        "id": str(s.id),
        "from": str(s.from_user_id),
        "kind": s.kind,
        "payload": s.payload or {},
        "created_at": s.created_at.isoformat() if s.created_at else None,
    } for s in rows]


def invites_for_me(db, user_id) -> list[dict]:
    rows = db.execute(
        select(CallParticipant, Call).join(Call, Call.id == CallParticipant.call_id).where(
            CallParticipant.user_id == user_id,
            CallParticipant.status == "invited",
            Call.status == "accepted",
        ).order_by(desc(CallParticipant.created_at)).limit(5)
    ).all()
    out = []
    for p, c in rows:
        inviter = db.get(User, p.invited_by) if p.invited_by else None
        pr = db.get(Profile, p.invited_by) if p.invited_by else None
        out.append({
            "call_id": str(c.id),
            "kind": c.kind,
            "from": {
                "user_id": str(inviter.id) if inviter else None,
                "name": display_name(inviter, pr) if inviter else "Someone",
                "avatar_url": pr.avatar_url if pr else None,
            },
        })
    return out
