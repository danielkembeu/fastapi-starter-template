"""Sondes de santé : live / startup / ready."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel.pool import StaticPool

from app.core import health
from app.core.health import state
from app.server import server


@pytest.fixture(autouse=True)
def _migrated_database(engine):
    """Sur PostgreSQL, la base de test est créée par `create_all` (sans Alembic) : on y simule le suivi
    de révision d'une base migrée, que la sonde de santé exige. SQLite n'a pas ce suivi (schéma « skipped »)."""
    if engine.dialect.name != "postgresql":
        yield
        return
    revision = health.expected_revision()
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        )
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(text("INSERT INTO alembic_version VALUES (:r)"), {"r": revision})
    yield
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def expected_schema_status(engine) -> str:
    return "ok" if engine.dialect.name == "postgresql" else "skipped"


@pytest.fixture(autouse=True)
def _fresh_health_state():
    health.reset_cache()
    state.started = False
    yield
    health.reset_cache()
    state.started = False


def test_live_answers_without_touching_any_dependency(client, monkeypatch):
    """Si `live` interrogeait la base, un hoquet de celle-ci ferait redémarrer tous les conteneurs."""

    def explode():
        raise AssertionError("live ne doit utiliser aucune dépendance")

    monkeypatch.setattr(health.database, "engine", property(explode), raising=False)
    r = client.get("/health/live")
    assert (r.status_code, r.json()) == (200, {"status": "ok"})


def test_live_stays_up_even_when_the_database_is_down(client, monkeypatch):
    broken = create_engine(
        "postgresql://nobody:nothing@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    monkeypatch.setattr(health.database, "engine", broken)
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503


def test_startup_reports_starting_until_the_lifespan_finishes(client):
    assert client.get("/health/startup").status_code == 503
    assert client.get("/health/startup").json() == {"status": "starting"}
    health.mark_started()
    assert client.get("/health/startup").json() == {"status": "ok"}


def test_the_real_lifespan_marks_the_app_as_started():
    assert state.started is False
    with TestClient(server) as started_client:
        assert started_client.get("/health/startup").status_code == 200
    assert state.started is True


def test_ready_is_ok_with_a_working_database(client, engine):
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["database"]["latency_ms"] >= 0
    # SQLite : pas de table alembic_version (« skipped ») ; PostgreSQL : révision comparée à la tête (« ok »)
    assert body["checks"]["schema"]["status"] == expected_schema_status(engine)


def test_ready_is_503_when_the_database_is_unreachable(client, monkeypatch):
    broken = create_engine(
        "postgresql://nobody:nothing@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    monkeypatch.setattr(health.database, "engine", broken)

    r = client.get("/health/ready")

    assert r.status_code == 503
    assert r.json()["status"] == "down"
    assert r.json()["checks"]["database"]["status"] == "down"


def test_ready_flags_a_database_behind_the_deployed_code(client, monkeypatch):
    """Le désalignement code/schéma qui avait bloqué le déploiement doit retirer l'API de la rotation."""
    monkeypatch.setattr(
        health,
        "_check_database",
        lambda: {"latency_ms": 1.0, "revision": "old_rev", "dialect": "postgresql"},
    )
    monkeypatch.setattr(health, "expected_revision", lambda: "new_rev")

    r = client.get("/health/ready")

    assert r.status_code == 503
    schema = r.json()["checks"]["schema"]
    assert (schema["status"], schema["current"], schema["expected"]) == (
        "outdated",
        "old_rev",
        "new_rev",
    )


def test_ready_accepts_a_database_at_the_expected_revision(client, monkeypatch):
    monkeypatch.setattr(
        health,
        "_check_database",
        lambda: {"latency_ms": 1.0, "revision": "head_rev", "dialect": "postgresql"},
    )
    monkeypatch.setattr(health, "expected_revision", lambda: "head_rev")
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"]["schema"]["status"] == "ok"


def test_a_slow_dependency_cannot_hang_the_probe(client, monkeypatch):
    import time

    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.2)

    def slow():
        time.sleep(1.0)
        return {"latency_ms": 1.0, "revision": None, "dialect": "sqlite"}

    monkeypatch.setattr(health, "_check_database", slow)
    started = time.perf_counter()
    r = client.get("/health/ready")
    assert time.perf_counter() - started < 0.9  # n'attend pas la dépendance
    assert r.status_code == 503
    assert r.json()["checks"]["database"]["error"] == "timeout"


def test_results_are_cached_so_probes_do_not_hammer_the_database(client, monkeypatch):
    calls = []

    def counted():
        calls.append(1)
        return {"latency_ms": 1.0, "revision": None, "dialect": "sqlite"}

    monkeypatch.setattr(health, "_check_database", counted)
    for _ in range(5):
        client.get("/health/ready")
    assert len(calls) == 1


def test_ready_checks_redis_when_the_rate_limiter_uses_it(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_STORAGE_URI", "redis://127.0.0.1:1/0")
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["redis"]["status"] == "down"


def test_public_callers_get_no_details_in_exposed_environments(client, monkeypatch):
    """Ni version, ni latence, ni état des dépendances : de quoi guider un attaquant."""
    monkeypatch.setattr(
        "app.core.config.settings.ENVIRONMENT",
        __import__("app.core.config", fromlist=["Environment"]).Environment.PRODUCTION,
    )
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_details_are_available_with_the_health_token(client, monkeypatch):
    from app.core.config import Environment

    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", Environment.PRODUCTION)
    monkeypatch.setattr("app.core.config.settings.HEALTH_DETAIL_TOKEN", "s3cret-token")

    wrong = client.get("/health/ready", headers={"X-Health-Token": "nope"})
    right = client.get("/health/ready", headers={"X-Health-Token": "s3cret-token"})

    assert wrong.json() == {"status": "ok"}
    assert "checks" in right.json()


def test_probes_are_exempt_from_rate_limiting(client, rate_limit):
    codes = {client.get("/health/live").status_code for _ in range(300)}
    assert codes == {200}


def test_health_routes_are_hidden_from_the_public_api_docs():
    paths = server.openapi()["paths"] if server.openapi_url else {}
    assert not any(p.startswith("/health") for p in paths)


# ---- Backend MongoDB et Redis ----------------------------------------------------------


def test_ready_checks_mongodb_instead_of_sql_when_it_is_the_selected_backend(client, monkeypatch):
    from app.core.config import DatabaseBackend

    monkeypatch.setattr("app.core.config.settings.DATABASE_BACKEND", DatabaseBackend.MONGODB)
    monkeypatch.setattr(health.mongo, "ping", lambda: None)
    monkeypatch.setattr(
        health.database, "engine", property(lambda: (_ for _ in ()).throw(AssertionError))
    )

    r = client.get("/health/ready")

    assert r.status_code == 200
    assert r.json()["checks"]["database"]["dialect"] == "mongodb"
    assert r.json()["checks"]["schema"]["status"] == "skipped"


def test_ready_is_503_when_mongodb_is_unreachable(client, monkeypatch):
    from app.core.config import DatabaseBackend

    def unreachable():
        raise ConnectionError("injoignable")

    monkeypatch.setattr("app.core.config.settings.DATABASE_BACKEND", DatabaseBackend.MONGODB)
    monkeypatch.setattr(health.mongo, "ping", unreachable)

    r = client.get("/health/ready")

    assert r.status_code == 503
    assert r.json()["checks"]["database"]["status"] == "down"


def test_ready_checks_redis_when_it_is_configured(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr(health, "_check_redis", lambda: {"latency_ms": 1.0})
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"]["redis"]["status"] == "ok"


def test_ready_is_503_when_the_configured_redis_is_down(client, monkeypatch):
    def down():
        raise ConnectionError

    monkeypatch.setattr("app.core.config.settings.REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setattr(health, "_check_redis", down)
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["redis"]["status"] == "down"
