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

engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=180,
    pool_size=2,
    max_overflow=2,
    future=True,
    connect_args={"connect_timeout": 10},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
