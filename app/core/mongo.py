"""Couche MongoDB (PyMongo), sélectionnée par `DATABASE_BACKEND=mongodb`.

Dépendance optionnelle : `pip install -r requirements-mongo.txt`. L'import de `pymongo` est paresseux
pour qu'un projet PostgreSQL n'ait pas à l'installer.

Le client PyMongo est thread-safe et gère son propre pool : on en crée **un seul** par processus.
"""

from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends

from app.core.config import settings


@lru_cache(maxsize=1)
def get_mongo_client() -> Any:
    from pymongo import MongoClient

    return MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=settings.MONGODB_TIMEOUT_MS)


def get_mongo_db() -> Any:
    """Base MongoDB de l'application (dépendance FastAPI)."""
    return get_mongo_client()[settings.MONGODB_DB_NAME]


MongoDBDep = Annotated[Any, Depends(get_mongo_db)]


def ping() -> None:
    """Lève si MongoDB est injoignable (utilisé par la sonde `/health/ready`)."""
    get_mongo_client().admin.command("ping")
