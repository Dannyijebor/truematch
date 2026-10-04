import httpx
from dateutil import parser as dtparser


def _parse_dt(s):
    if not s:
        return None
    try:
        return dtparser.parse(s)
    except Exception:
        return None


async def fetch_greenhouse(token):
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "TrueMatch/0.3"}) as c:
        r = await c.get(url)
        if r.status_code != 200:
            return []
        data = r.json()
    out = []
    for j in data.get("jobs", []):
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
            "posted_at": _parse_dt(j.get("updated_at") or j.get("created_at")),
            "raw": j,
        })
    return out


async def fetch_lever(token):
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "TrueMatch/0.3"}) as c:
        r = await c.get(url)
        if r.status_code != 200:
            return []
        data = r.json()
    out = []
    for j in data:
        loc = j.get("categories", {}).get("location", "") or ""
        out.append({
            "source": "lever",
            "source_id": j["id"],
            "title": j["text"],
            "company_name": token,
            "location": loc,
            "remote": "remote" in loc.lower(),
            "description_html": j.get("descriptionHtml", "") or j.get("description", ""),
            "apply_url": j.get("applyUrl") or j.get("hostedUrl"),
            "posted_at": _parse_dt(j.get("createdAt")),
            "raw": j,
        })
    return out


async def fetch_ashby(token):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "TrueMatch/0.3"}) as c:
        r = await c.get(url)
        if r.status_code != 200:
            return []
        data = r.json()
    out = []
    for j in data.get("jobs", []):
        loc = j.get("location", "") or ""
        out.append({
            "source": "ashby",
            "source_id": j["id"],
            "title": j["title"],
            "company_name": token,
            "location": loc,
            "remote": j.get("isRemote", False) or "remote" in loc.lower(),
            "description_html": j.get("descriptionHtml", "") or j.get("description", ""),
            "apply_url": j.get("jobUrl"),
            "posted_at": _parse_dt(j.get("publishedAt")),
            "raw": j,
        })
    return out


async def fetch_workable(token):
    url = f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "TrueMatch/0.3"}) as c:
        r = await c.get(url)
        if r.status_code != 200:
            return []
        data = r.json()
    out = []
    for j in data.get("jobs", []):
        loc = f'{j.get("city","")} {j.get("country","")}'.strip()
        out.append({
            "source": "workable",
            "source_id": j["id"],
            "title": j["title"],
            "company_name": token,
            "location": loc,
            "remote": j.get("telecommuting", False),
            "description_html": j.get("description", ""),
            "apply_url": j.get("url"),
            "posted_at": _parse_dt(j.get("published_on")),
            "raw": j,
        })
    return out


ADAPTERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workable": fetch_workable,
}
