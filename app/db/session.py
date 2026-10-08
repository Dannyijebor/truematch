import os, socket
# On Termux (flaky 4G), cache DNS to avoid lookup failures.
# On cloud hosts, Neon's Cloudflare endpoint rotates IPs, so caching breaks
# connections. Only enable when TM_DNS_CACHE=1.
if os.getenv("TM_DNS_CACHE") == "1":
    _orig_getaddrinfo = socket.getaddrinfo
    _dns_cache = {}
    def _cached_getaddrinfo(*args, **kwargs):
        key = args[0] if args else None
        if key in _dns_cache:
            return _dns_cache[key]
        result = _orig_getaddrinfo(*args, **kwargs)
        _dns_cache[key] = result
        return result
    socket.getaddrinfo = _cached_getaddrinfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app import config

import os as _os

# Serverless platforms (Vercel, Lambda) run each request in its own process
# with its own connection pool. Aiven free tier caps total connections at 20,
# so pooling quickly exhausts the limit. NullPool = one connection per request,
# closed immediately — safe under any concurrency.
_IS_SERVERLESS = bool(_os.getenv("VERCEL") or _os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

if _IS_SERVERLESS:
    from sqlalchemy.pool import NullPool
    engine = create_engine(
        config.DATABASE_URL,
        poolclass=NullPool,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": 10},
    )
else:
    engine = create_engine(
        config.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=180,
        pool_size=2,
        max_overflow=2,
        future=True,
        connect_args={"connect_timeout": 6, "keepalives": 1, "keepalives_idle": 30},
    )
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# Warm up the Neon connection at module import time.
# This runs once when the Vercel function cold-starts, so that by the time
# a real request hits an endpoint, both Vercel and Neon are already warm.
def _warm_up():
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        # Silent — the app still works if warm-up fails (a later request retries)
        pass


try:
    _warm_up()
except Exception:
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
