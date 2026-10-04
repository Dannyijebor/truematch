import os
import time
import httpx

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_last_sent = 0.0
MIN_INTERVAL = 1.0


def _token():
    t = os.getenv("TELEGRAM_BOT_TOKEN")
    if not t:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
    return t


def send_telegram(chat_id: str | int, text: str) -> dict:
    global _last_sent
    delta = time.time() - _last_sent
    if delta < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - delta)

    token = _token()
    r = httpx.post(
        TELEGRAM_API.format(token=token),
        json={
            "chat_id": str(chat_id),
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    _last_sent = time.time()
    if r.status_code != 200:
        raise RuntimeError(f"telegram {r.status_code}: {r.text[:200]}")
    return r.json()


def notify_match(chat_id, title, company, score, link):
    body = (
        f"*New match: {score:.0f}%*\n\n"
        f"*{title}*\n"
        f"{company}\n\n"
        f"Your tailored application is ready.\n"
        f"[Open apply packet]({link})"
    )
    return send_telegram(chat_id, body)


def notify_packet_ready(chat_id, title, company, link):
    body = (
        f"*Application ready*\n\n"
        f"*{title}*\n"
        f"{company}\n\n"
        f"[View packet]({link})"
    )
    return send_telegram(chat_id, body)
