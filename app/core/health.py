"""Sondes de santé pour l'orchestrateur (Docker, reverse proxy, supervision).

Trois questions distinctes, volontairement séparées :

- `/health/live`    : le processus répond-il ? Ne touche AUCUNE dépendance. Si elle interrogeait la
  base, un hoquet de quelques secondes ferait échouer la sonde de tous les conteneurs d'un coup :
  ils redémarreraient ensemble et se reconnecteraient en même temps sur une base déjà en difficulté.
- `/health/startup` : le démarrage est-il terminé ? Évite qu'un démarrage lent soit tué par `live`.
- `/health/ready`   : peut-on servir du trafic ? Base joignable, Redis si configuré, et schéma à la
  révision Alembic attendue par le code déployé. En cas d'échec on sort de la rotation, sans redémarrer.

Les services tiers (stockage d'images, e-mails…) ne sont volontairement PAS vérifiés : c'est un tiers, sa panne ne doit pas devenir la nôtre
(les uploads dégradent déjà proprement en 502/503).
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text

from app.core import database, mongo
from app.core.config import settings
from app.core.ratelimit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"], include_in_schema=False)

CHECK_TIMEOUT_SECONDS = 2.0
CACHE_TTL_SECONDS = 3.0
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class HealthState:
    started: bool = False
    cached_at: float = 0.0
    cached: dict[str, Any] | None = None
    expected_revision: str | None = field(default=None)


state = HealthState()


def mark_started() -> None:
    state.started = True


# ---- Vérifications -------------------------------------------------------------------


def expected_revision() -> str | None:
    """Révision Alembic attendue par le code déployé (None si indéterminable)."""
    if state.expected_revision is None:
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            config = Config(str(PROJECT_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
            state.expected_revision = ScriptDirectory.from_config(config).get_current_head()
        except Exception:
            logger.exception("Impossible de déterminer la révision Alembic attendue")
            return None
    return state.expected_revision


def _check_database() -> dict[str, Any]:
    started = time.perf_counter()
    with database.engine.connect() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SET LOCAL statement_timeout = 2000"))

        connection.execute(text("SELECT 1"))
        revision = None

        if connection.dialect.name == "postgresql":
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()

    return {
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "revision": revision,
        "dialect": database.engine.dialect.name,
    }


def _check_mongodb() -> dict[str, Any]:
    started = time.perf_counter()
    mongo.ping()

    return {"latency_ms": round((time.perf_counter() - started) * 1000, 1), "dialect": "mongodb"}


def _check_redis() -> dict[str, Any]:
    import redis

    started = time.perf_counter()
    url = settings.RATE_LIMIT_STORAGE_URI
    if not url.startswith("redis"):
        url = settings.REDIS_URL
    client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)

    try:
        client.ping()
    finally:
        client.close()

    return {"latency_ms": round((time.perf_counter() - started) * 1000, 1)}


async def _run(check: Callable[[], dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    try:
        result = await asyncio.wait_for(run_in_threadpool(check), CHECK_TIMEOUT_SECONDS)

        return True, result
    except TimeoutError:
        return False, {"error": "timeout"}
    except Exception as exc:
        logger.warning(
            "Vérification de santé en échec (%s) : %s", check.__name__, type(exc).__name__
        )
        return False, {"error": type(exc).__name__}


async def evaluate() -> dict[str, Any]:
    """Exécute les vérifications de disponibilité (résultat mis en cache quelques secondes)."""
    now = time.monotonic()
    if state.cached is not None and now - state.cached_at < CACHE_TTL_SECONDS:
        return state.cached

    checks: dict[str, dict[str, Any]] = {}

    db_ok, db = await _run(_check_mongodb if settings.uses_mongodb else _check_database)
    checks["database"] = {"status": "ok" if db_ok else "down", **db}

    if db_ok and db.get("dialect") == "postgresql":
        expected, current = expected_revision(), db.get("revision")
        in_sync = expected is not None and current == expected
        checks["schema"] = {
            "status": "ok" if in_sync else "outdated",
            "current": current,
            "expected": expected,
        }
    else:
        checks["schema"] = {"status": "skipped"}

    redis_url = next(
        (u for u in (settings.RATE_LIMIT_STORAGE_URI, settings.REDIS_URL) if u.startswith("redis")),
        None,
    )
    if redis_url:
        redis_ok, redis_info = await _run(_check_redis)
        checks["redis"] = {"status": "ok" if redis_ok else "down", **redis_info}

    healthy = all(c["status"] in ("ok", "skipped") for c in checks.values())
    result = {"status": "ok" if healthy else "down", "checks": checks}
    state.cached, state.cached_at = result, now

    return result


def reset_cache() -> None:
    state.cached = None
    state.cached_at = 0.0


def _detail_allowed(token: str | None) -> bool:
    if settings.HEALTH_DETAIL_TOKEN:
        return token == settings.HEALTH_DETAIL_TOKEN

    return not settings.is_exposed


def _present(result: dict[str, Any], token: str | None) -> dict[str, Any]:
    """Public : « ok » ou « down » seulement. Les versions et détails guident un attaquant."""

    if _detail_allowed(token):
        return result

    return {"status": result["status"]}


# ---- Routes --------------------------------------------------------------------------


@router.get("/live")
@limiter.exempt
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/startup")
@limiter.exempt
def startup(response: Response) -> dict[str, str]:
    if not state.started:
        response.status_code = 503
        return {"status": "starting"}
    return {"status": "ok"}


@router.get("/ready")
@limiter.exempt
async def ready(
    response: Response, x_health_token: str | None = Header(default=None)
) -> dict[str, Any]:
    result = await evaluate()
    if result["status"] != "ok":
        response.status_code = 503
    return _present(result, x_health_token)
