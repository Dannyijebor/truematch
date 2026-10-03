import httpx
from dateutil import parser as dtparser

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

async def fetch(token: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "TrueMatch/0.1"}) as c:
        r = await c.get(API.format(token=token))
        r.raise_for_status()
        data = r.json()

    out = []
    for j in data.get("jobs", []):
        posted = j.get("updated_at") or j.get("created_at")
        try:
            posted_dt = dtparser.parse(posted) if posted else None
        except Exception:
            posted_dt = None

        loc = (j.get("location") or {}).get("name", "") or ""
        out.append({
            "source": "greenhouse",
            "source_id": str(j["id"]),
            "title": j["title"],
            "company_name": token,
            "location": loc,
            "remote": "remote" in loc.lower(),
            "description_html": j.get("content", ""),
            "apply_url": j.get("absolute_url"),
            "posted_at": posted_dt,
            "raw": j,
        })
    return out
