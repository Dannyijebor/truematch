"""Weekly: promote any variant beating control by 15%+ with 100+ impressions."""
from app.db.session import SessionLocal
from app.db.models import ExperimentVariant
from app.experiments import auto_promote_if_winner
from sqlalchemy import select

db = SessionLocal()
try:
    names = list(db.execute(select(ExperimentVariant.experiment).distinct()).scalars().all())
    for name in names:
        result = auto_promote_if_winner(db, name)
        print(f"{name}: {result}")
finally:
    db.close()
