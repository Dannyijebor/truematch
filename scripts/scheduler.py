import asyncio
import time
from datetime import datetime
from app.ingestion.run_all import run, all_pairs

INTERVAL_SECONDS = 6 * 60 * 60  # 6 hours


async def loop():
    while True:
        print(f"\n[{datetime.now().isoformat()}] starting ingestion run...")
        pairs = all_pairs()
        try:
            await run(pairs)
        except Exception as e:
            print(f"run failed: {e}")
        print(f"[{datetime.now().isoformat()}] sleeping {INTERVAL_SECONDS}s")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(loop())
