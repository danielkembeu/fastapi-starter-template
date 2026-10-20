"""Couche MongoDB : import paresseux, un seul client par processus, sonde de santé."""

import sys
import types

import pytest

from app.core import mongo


@pytest.fixture(autouse=True)
def _fresh_client():
    mongo.get_mongo_client.cache_clear()
    yield
    mongo.get_mongo_client.cache_clear()


@pytest.fixture(name="fake_pymongo")
def fake_pymongo_fixture(monkeypatch):
    created = []

    class FakeClient:
        def __init__(self, url, **kwargs):
            self.url, self.kwargs = url, kwargs
            self.pings = 0
            self.admin = types.SimpleNamespace(command=self._command)
            created.append(self)

        def _command(self, name):
            assert name == "ping"
            self.pings += 1

        def __getitem__(self, name):
            return f"db:{name}"

    module = types.ModuleType("pymongo")
    module.MongoClient = FakeClient
    monkeypatch.setitem(sys.modules, "pymongo", module)
    monkeypatch.setattr("app.core.config.settings.MONGODB_URL", "mongodb://127.0.0.1:27017")
    monkeypatch.setattr("app.core.config.settings.MONGODB_DB_NAME", "appdb")
    monkeypatch.setattr("app.core.config.settings.MONGODB_TIMEOUT_MS", 1234)
    return created


def test_the_client_is_created_once_with_the_configured_timeout(fake_pymongo):
    first, second = mongo.get_mongo_client(), mongo.get_mongo_client()
    assert first is second and len(fake_pymongo) == 1
    assert fake_pymongo[0].kwargs == {"serverSelectionTimeoutMS": 1234}


def test_the_dependency_returns_the_configured_database(fake_pymongo):
    assert mongo.get_mongo_db() == "db:appdb"


def test_ping_reaches_the_server(fake_pymongo):
    mongo.ping()
    assert fake_pymongo[0].pings == 1


def test_importing_the_module_does_not_require_pymongo(monkeypatch):
    """Un projet PostgreSQL n'installe pas pymongo : seul l'USAGE du client l'exige."""
    monkeypatch.setitem(sys.modules, "pymongo", None)
    with pytest.raises(ImportError):
        mongo.get_mongo_client()
