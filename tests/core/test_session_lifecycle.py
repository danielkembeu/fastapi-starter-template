"""Les endpoints doivent fonctionner avec le VRAI cycle de vie d'une session par requête.

Les autres tests partagent une même session ouverte : une relation chargée paresseusement après la
fermeture de la session (DetachedInstanceError) n'y est jamais détectée, alors qu'elle donnerait un
500 en production. Ici, chaque requête ouvre et ferme sa propre session, comme en production.

À chaque nouvelle ressource : ajouter ses routes de lecture à `test_endpoints_serialize_…`.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

import app.core.database as _db
from app.server import server
from tests.helpers.auth import PASSWORD, bearer
from tests.helpers.factories import make_project


@pytest.fixture(name="real_client")
def real_client_fixture(engine, monkeypatch):
    monkeypatch.setattr(_db, "engine", engine)
    server.dependency_overrides.clear()
    yield TestClient(server, raise_server_exceptions=True)


@pytest.fixture(name="seed")
def seed_fixture(engine, users):
    """Jeu de données minimal couvrant les relations sérialisées par l'API."""
    with Session(engine) as s:
        user = users.user()
        admin = users.admin()
        project = make_project(s, user)
    return {"user": user, "admin": admin, "project": project}


@pytest.mark.parametrize(
    ("role", "path"),
    [
        ("user", "/api/v1/auth/me"),
        ("user", "/api/v1/projects"),
        ("admin", "/api/v1/projects"),
        ("admin", "/api/v1/admin/audit-logs"),
    ],
)
def test_endpoints_serialize_correctly_with_a_real_session_lifecycle(real_client, seed, role, path):
    response = real_client.get(path, headers=bearer(seed[role]))
    assert response.status_code == 200, response.text


def test_single_resource_is_serialized_after_the_session_closes(real_client, seed):
    response = real_client.get(
        f"/api/v1/projects/{seed['project'].id}", headers=bearer(seed["user"])
    )
    assert response.status_code == 200, response.text
    assert response.json()["owner_id"] == str(seed["user"].id)


def test_write_flow_works_with_real_sessions(real_client, users):
    user = users.user()
    created = real_client.post("/api/v1/projects", json={"name": "Alpha"}, headers=bearer(user))
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    activated = real_client.post(
        f"/api/v1/projects/{project_id}/status", json={"status": "active"}, headers=bearer(user)
    )
    assert activated.status_code == 200, activated.text
    assert (
        real_client.delete(f"/api/v1/projects/{project_id}", headers=bearer(user)).status_code
        == 204
    )


def test_login_refresh_logout_with_real_sessions(real_client, users):
    user = users.user()
    login = real_client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    refresh = real_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
    )
    assert refresh.status_code == 200, refresh.text
    assert refresh.json()["user"]["email"] == user.email
    logout = real_client.post(
        "/api/v1/auth/logout", json={"refresh_token": refresh.json()["refresh_token"]}
    )
    assert logout.status_code == 200
