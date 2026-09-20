"""Explicit PostgreSQL configuration, independent of SAM startup."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class PersistenceSettings:
    database_url: str = field(repr=False)
    storage_root: Path

    @classmethod
    def from_env(cls) -> "PersistenceSettings":
        url = os.environ.get("DATABASE_URL", "").strip()
        if not url:
            raise ValueError("DATABASE_URL is required for persistence.")
        if make_url(url).drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use postgresql+psycopg.")
        root = Path(os.environ.get("STORAGE_ROOT", "storage")).expanduser().resolve()
        return cls(url, root)


def create_database_engine(settings: PersistenceSettings) -> Engine:
    if make_url(settings.database_url).drivername != "postgresql+psycopg":
        raise ValueError("DATABASE_URL must use postgresql+psycopg.")
    return create_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Use factory.begin() for commit/rollback and automatic session close."""
    return sessionmaker(engine, expire_on_commit=False)
