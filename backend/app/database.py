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

engine = create_engine(_db_url, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
