from app.db.session import SessionLocal
from app.stories import cleanup_expired

db = SessionLocal()
try:
    n = cleanup_expired(db)
    print(f"deleted {n} expired stories")
finally:
    db.close()
