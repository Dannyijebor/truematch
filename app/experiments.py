"""
Variant testing + feedback engine.

Concepts:
- An experiment has 2+ variants (A/B/n), one is the control.
- Each user is assigned to exactly one variant, deterministically (hash of user_id+experiment).
- Events: impression → click → convert. Tracked per variant.
- Feedback: 👍/👎 + optional comment.
- Weekly job computes win rate; when a variant beats control by +15% at ≥100 events, it can be auto-promoted.
"""
import hashlib
from datetime import datetime, timezone
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session
from app.db.models import ExperimentVariant, ExperimentStat, Feedback


# ---------- assignment ----------

def get_variants(db: Session, experiment: str) -> list[ExperimentVariant]:
    rows = db.execute(
        select(ExperimentVariant)
        .where(ExperimentVariant.experiment == experiment, ExperimentVariant.is_active == True)
        .order_by(ExperimentVariant.variant)
    ).scalars().all()
    return rows


def pick_variant(db: Session, user_id, experiment: str) -> ExperimentVariant | None:
    """Deterministic A/B assignment per (user, experiment)."""
    variants = get_variants(db, experiment)
    if not variants:
        return None
    if len(variants) == 1:
        return variants[0]

    h = hashlib.sha256(f"{user_id}:{experiment}".encode()).digest()
    # Convert first 4 bytes to 0-9999 range
    bucket = int.from_bytes(h[:4], "big") % 10000
    cumulative = 0
    total = sum(v.weight or 0 for v in variants) or 100
    for v in variants:
        cumulative += int((v.weight or 0) / total * 10000)
        if bucket < cumulative:
            return v
    return variants[-1]


def variant_config(db: Session, user_id, experiment: str, default: dict | None = None) -> dict:
    """Return the variant's config dict plus variant name. Templates call this."""
    v = pick_variant(db, user_id, experiment)
    if not v:
        return {"variant": None, "config": default or {}}
    return {"variant": v.variant, "config": {**(default or {}), **(v.config or {})}}


# ---------- events ----------

def track(db: Session, experiment: str, variant: str, event: str, user_id=None, meta: dict | None = None):
    db.add(ExperimentStat(
        experiment=experiment, variant=variant, event=event,
        user_id=user_id, meta=meta or {},
    ))
    db.commit()


def stats(db: Session, experiment: str, days: int = 30) -> dict:
    """Return conversion stats per variant for the last N days."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(
            ExperimentStat.variant,
            ExperimentStat.event,
            func.count(ExperimentStat.id).label("n"),
        )
        .where(ExperimentStat.experiment == experiment, ExperimentStat.created_at > cutoff)
        .group_by(ExperimentStat.variant, ExperimentStat.event)
    ).all()

    out = {}
    for v, ev, n in rows:
        out.setdefault(v, {"impression": 0, "click": 0, "convert": 0})
        out[v][ev] = n

    # Compute rates
    for v, d in out.items():
        imp = d.get("impression", 0)
        clk = d.get("click", 0)
        cnv = d.get("convert", 0)
        d["click_rate"] = round(clk / imp * 100, 2) if imp else 0
        d["convert_rate"] = round(cnv / imp * 100, 2) if imp else 0

    return out


# ---------- feedback ----------

def record_feedback(db: Session, user_id, page: str, sentiment: str, comment: str | None = None,
                    experiment: str | None = None, variant: str | None = None) -> Feedback:
    f = Feedback(
        user_id=user_id, page=page, sentiment=sentiment,
        comment=(comment or "").strip()[:2000] or None,
        experiment=experiment, variant=variant,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def feedback_summary(db: Session, days: int = 30) -> dict:
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(Feedback.page, Feedback.sentiment, func.count(Feedback.id))
        .where(Feedback.created_at > cutoff)
        .group_by(Feedback.page, Feedback.sentiment)
    ).all()
    out = {}
    for page, sent, n in rows:
        out.setdefault(page, {"up": 0, "down": 0})
        out[page][sent] = n
    return out


def recent_feedback(db: Session, limit: int = 50) -> list[dict]:
    rows = db.execute(
        select(Feedback).order_by(desc(Feedback.created_at)).limit(limit)
    ).scalars().all()
    return [{
        "id": str(f.id),
        "page": f.page,
        "sentiment": f.sentiment,
        "comment": f.comment,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    } for f in rows]


# ---------- auto-promote ----------

def auto_promote_if_winner(db: Session, experiment: str, min_events: int = 100, margin_pct: float = 15.0) -> dict:
    """If a non-control variant beats control by margin_pct with >= min_events, bump its weight to 90%.
    Returns a dict describing what changed (or why nothing changed)."""
    variants = get_variants(db, experiment)
    if len(variants) < 2:
        return {"promoted": False, "reason": "need 2+ active variants"}

    s = stats(db, experiment, days=30)
    control = next((v for v in variants if v.is_control), variants[0])
    ctrl_events = s.get(control.variant, {}).get("impression", 0)
    if ctrl_events < min_events:
        return {"promoted": False, "reason": f"control needs {min_events} impressions, has {ctrl_events}"}

    ctrl_rate = s.get(control.variant, {}).get("convert_rate", 0)
    best = None
    for v in variants:
        if v.variant == control.variant:
            continue
        r = s.get(v.variant, {}).get("convert_rate", 0)
        if ctrl_rate <= 0:
            continue
        lift = (r - ctrl_rate) / ctrl_rate * 100
        if lift >= margin_pct and s.get(v.variant, {}).get("impression", 0) >= min_events:
            if best is None or lift > best[1]:
                best = (v, lift)

    if not best:
        return {"promoted": False, "reason": f"no variant beats control by {margin_pct}%"}

    winner, lift = best
    for v in variants:
        if v.variant == winner.variant:
            v.weight = 90
        elif v.is_control:
            v.weight = 10
        else:
            v.weight = 0
    db.commit()

    return {
        "promoted": True,
        "winner": winner.variant,
        "lift_pct": round(lift, 1),
        "control_variant": control.variant,
    }
