import asyncio
import sys
from app.db.session import SessionLocal
from app.ingestion import greenhouse
from app.ingestion.pipeline import upsert_jobs

SEEDS = [
    "stripe", "figma", "airbnb", "coinbase",
    "databricks", "discord", "reddit", "instacart",
    "gitlab", "hashicorp", "cloudflare", "samsara",
]


async def run(tokens):
    all_jobs = []
    for t in tokens:
        try:
            jobs = await greenhouse.fetch(t)
            print(f"  {t}: {len(jobs)} jobs")
            all_jobs.extend(jobs)
        except Exception as e:
            print(f"  {t}: SKIP ({e.__class__.__name__})")

    print(f"\nTotal fetched: {len(all_jobs)}. Upserting...")
    db = SessionLocal()
    try:
        new, upd = upsert_jobs(db, all_jobs)
        print(f"\nDone. {new} new, {upd} updated.")
    finally:
        db.close()


if __name__ == "__main__":
    tokens = sys.argv[1:] or SEEDS
    asyncio.run(run(tokens))
