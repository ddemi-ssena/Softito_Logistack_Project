"""SQLAlchemy engine and request-scoped session dependency."""

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl"))
from extract import connection_settings  # noqa: E402

_settings = connection_settings()
_url = URL.create(
    "postgresql+psycopg",
    username=_settings["user"],
    password=_settings["password"],
    host=_settings["host"],
    port=_settings["port"],
    database=_settings["dbname"],
)

engine = create_engine(_url, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
