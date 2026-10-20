"""Fixtures pytest : moteur SQLite éphémère + client FastAPI avec session override.

On force une configuration de test (`DATABASE_URL`, `SECRET_JWT`) AVANT d'importer
l'app. Les tables nécessaires aux tests sont créées manuellement (voir fixture
`engine`), indépendamment du schéma applicatif géré par Alembic.
"""

import os

# Doit être défini avant l'import de `app.core.config` (Settings).
# ENVIRONMENT=ci : aucun fichier .env.* n'est lu, les tests ne dépendent pas du poste.
os.environ["ENVIRONMENT"] = "ci"
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_JWT", "test-secret-do-not-use-in-prod")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
# Les variables d'environnement priment sur le fichier .env : garantit qu'aucun
# événement n'est envoyé à Sentry pendant les tests, même avec un .env local rempli.
os.environ["SENTRY_DSN"] = ""
# Le limiteur de débit est coupé par défaut ; les tests qui le vérifient le réactivent (fixture `rate_limit`).
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["BCRYPT_ROUNDS"] = "4"  # hachage rapide : seuls les tests y touchent

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

import app.core.database as _db
import app.modules
from app.server import server
from tests.helpers.auth import TestUsers


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(type_, compiler, **kw):
    """SQLite n'a pas JSONB : on le rend en JSON pour pouvoir créer toutes les tables."""
    return "JSON"


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(name="engine")
def engine_fixture(monkeypatch):
    """Base de test : SQLite en mémoire par défaut, PostgreSQL réel si TEST_DATABASE_URL est défini.

    Lancer aussi la suite sur PostgreSQL (`make test-pg`) vérifie ce que SQLite ne montre pas :
    types enum, JSONB, verrous et agrégations.
    """
    if TEST_DATABASE_URL:
        eng = create_engine(TEST_DATABASE_URL)
        SQLModel.metadata.drop_all(eng)
        SQLModel.metadata.create_all(eng)
        monkeypatch.setattr(_db, "engine", eng)  # écritures indépendantes (journal d'audit)
        yield eng
        SQLModel.metadata.drop_all(eng)
        eng.dispose()
        return

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(_db, "engine", eng)  # écritures indépendantes (journal d'audit)

    yield eng

    eng.dispose()


@pytest.fixture(name="session")
def session_fixture(engine):
    """Session SQLModel reliée à l'engine de test."""
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session):
    """TestClient FastAPI, dont la dépendance DB pointe sur la session de test."""

    def override_get_session():
        yield session

    server.dependency_overrides[_db.get_session] = override_get_session
    yield TestClient(server)

    server.dependency_overrides.clear()


@pytest.fixture(name="users")
def users_fixture(session):
    """Fabrique d'utilisateurs par rôle, avec leurs en-têtes d'authentification."""
    return TestUsers(session)


@pytest.fixture(name="rate_limit")
def rate_limit_fixture():
    """Active le limiteur de débit le temps d'un test, avec des compteurs vierges.

    L'état global du limiteur (activation, limites par défaut) est restauré ensuite : sans cela, un
    test qui le modifie fausserait silencieusement les suivants.
    """
    from app.core.ratelimit import limiter

    original_defaults = list(limiter._default_limits)
    limiter.reset()
    limiter.enabled = True
    yield limiter
    limiter.enabled = False
    limiter._default_limits = original_defaults
    limiter.reset()
