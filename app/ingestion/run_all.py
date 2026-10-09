import asyncio
import sys
from app.db.session import SessionLocal
from app.ingestion.adapters import ADAPTERS
from app.ingestion.registry import all_pairs
from app.ingestion.pipeline import upsert_jobs

CONCURRENCY = 8


async def fetch_one(source, token, sem):
    async with sem:
        try:
            jobs = await ADAPTERS[source](token)
            print(f"  {source}/{token}: {len(jobs)}")
            return jobs
        except Exception as e:
            print(f"  {source}/{token}: SKIP ({e.__class__.__name__})")
            return []


async def run(pairs):
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [fetch_one(s, t, sem) for s, t in pairs]
    results = await asyncio.gather(*tasks)
    all_jobs = []
    for r in results:
        all_jobs.extend(r)
    print(f"\nTotal fetched: {len(all_jobs)}. Upserting...")

    db = SessionLocal()
    try:
        new, upd = upsert_jobs(db, all_jobs)
        print(f"\nDone. {new} new, {upd} updated.")
    finally:
        db.close()



def mark_stale(db):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.db.models import Job
    cutoff = datetime.now(timezone.utc) - timedelta(days=60)
    r = db.execute(update(Job).where(Job.posted_at < cutoff, Job.is_active == True).values(is_active=False))
    db.commit()
    return r.rowcount or 0

if __name__ == "__main__":
    pairs = all_pairs()
    if len(sys.argv) > 1:
        limit = int(sys.argv[1])
        pairs = pairs[:limit]
    print(f"Fetching from {len(pairs)} sources...")
    asyncio.run(run(pairs))
