import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Load .env from the backend directory so DATABASE_URL is available
# whether the app is started via uvicorn, the scraper CLI, or alembic.
load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://grantrx:grantrx@localhost:5432/grantrx",
)

# Normalize the URL for psycopg3 (SQLAlchemy 2.x uses the "psycopg" driver).
# Accepts both "postgresql://..." and "postgresql+psycopg://..." forms.
_db_url = DATABASE_URL
if _db_url.startswith("postgresql://") and "+psycopg" not in _db_url:
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)

# Connection-pool hardening for hosted Postgres poolers (e.g. Supabase's
# session pooler), which silently reap idle client connections:
# - pool_pre_ping: validate each pooled connection with a cheap `SELECT 1`
#   before checkout; dead sockets are discarded and reconnected instead of
#   surfacing as a hung query.
# - pool_recycle=300: retire connections older than 5 minutes, below typical
#   pooler idle timeouts, so the pool refreshes before the server can reap.
ENGINE_KWARGS: dict = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

# TCP keepalives (psycopg3 → libpq params) let the OS detect half-open
# connections during long-running queries instead of waiting out TCP
# retransmit timeouts. Postgres-only — skipped for non-Postgres URLs.
if _db_url.startswith("postgresql"):
    ENGINE_KWARGS["connect_args"] = {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }

engine = create_engine(_db_url, future=True, **ENGINE_KWARGS)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
