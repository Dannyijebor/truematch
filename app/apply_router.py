import re

EMAIL_PATTERNS = [
    r"send your (?:resume|cv|application) to\s+([\w.+-]+@[\w-]+\.[\w.-]+)",
    r"email (?:us|your (?:resume|cv|application)) at\s+([\w.+-]+@[\w-]+\.[\w.-]+)",
    r"apply (?:by|via) email(?: to)?\s+([\w.+-]+@[\w-]+\.[\w.-]+)",
    r"contact\s+([\w.+-]+@[\w-]+\.[\w.-]+)",
]

BLOCKED = ["noreply@", "donotreply@", "no-reply@"]


def detect_apply_type(job) -> dict:
    text = ((job.description_text or "") + " " + (job.description_html or ""))[:20000]
    for pat in EMAIL_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            email = m.group(1).lower()
            if not any(b in email for b in BLOCKED):
                return {"type": "email", "email": email}
    return {"type": "deep_link", "email": None}
