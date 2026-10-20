"""Couche SQL (PostgreSQL / SQLModel).

Avec `DATABASE_BACKEND=mongodb`, aucun module SQL n'est monté (voir `app/server.py`) : un moteur SQLite
mémoire inerte (`settings.sql_url`) garde simplement les imports valides. La couche MongoDB est dans
`app/core/mongo.py`.
"""

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends
from sqlmodel import Session, create_engine

from app.core.config import settings

_engine_options: dict[str, Any] = {"echo": False, "pool_pre_ping": True, "pool_recycle": 300}

if not settings.sql_url.startswith("sqlite"):
    _engine_options.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
    )

engine = create_engine(settings.sql_url, **_engine_options)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


DBSessionDep = Annotated[Session, Depends(get_session)]
