"""Garantie structurelle : TOUTES les opérations laissent une trace.

1. `MUTATING_ROUTES` décide, pour chaque route qui modifie quelque chose, quelles actions d'audit elle
   produit — ou pourquoi elle est exemptée. Une route ajoutée sans décision fait échouer ce test.
2. Chaque action du catalogue est référencée dans le code (aucune action « morte »).
3. Un parcours complet de l'application produit réellement chacune des actions du catalogue.

À chaque nouvelle ressource : déclarer ses routes ici, ajouter ses actions à `AuditAction`, et les faire
produire par le parcours de `test_a_full_journey_…`.
"""

import re
from pathlib import Path

from fastapi.routing import APIRoute

from app.modules.audit.enums import AuditAction as A
from app.modules.users.service import UserService
from app.server import server
from tests.helpers.audit import actions
from tests.helpers.auth import PASSWORD, bearer, register_payload

EXEMPT = "exempt"

# route -> (actions produites)  |  (EXEMPT, raison)
MUTATING_ROUTES: dict[tuple[str, str], tuple[A, ...] | tuple[str, str]] = {
    ("POST", "/api/v1/auth/register"): (A.AUTH_REGISTER,),
    ("POST", "/api/v1/auth/login"): (A.AUTH_LOGIN, A.AUTH_LOGIN_FAILED, A.AUTH_ACCOUNT_LOCKED),
    ("POST", "/api/v1/auth/token"): (A.AUTH_LOGIN, A.AUTH_LOGIN_FAILED),
    ("POST", "/api/v1/auth/refresh"): (A.AUTH_TOKEN_REFRESHED, A.AUTH_TOKEN_REUSE_DETECTED),
    ("POST", "/api/v1/auth/logout"): (A.AUTH_LOGOUT,),
    ("POST", "/api/v1/projects"): (A.PROJECT_CREATED,),
    ("PATCH", "/api/v1/projects/{project_id}"): (A.PROJECT_UPDATED,),
    ("POST", "/api/v1/projects/{project_id}/status"): (A.PROJECT_STATUS_CHANGED,),
    ("DELETE", "/api/v1/projects/{project_id}"): (A.PROJECT_DELETED,),
}
READS_THAT_ARE_AUDITED = {
    ("GET", "/api/v1/admin/audit-logs"): (A.AUDIT_VIEWED,),
}
# Produites par un mécanisme central, pas par une route précise.
CENTRAL_ACTIONS = {A.ACCESS_DENIED, A.USER_ADMIN_CREATED}  # ce dernier : script, sans route


def _mutating_routes() -> set[tuple[str, str]]:
    found = set()
    for route in server.routes:
        if isinstance(route, APIRoute) and route.path not in {"/docs", "/openapi.json"}:
            for method in route.methods & {"POST", "PUT", "PATCH", "DELETE"}:
                found.add((method, route.path))
    return found


def test_every_mutating_route_has_an_audit_decision():
    """Ajouter une route qui modifie des données sans dire comment elle est tracée fait échouer ce test."""
    assert _mutating_routes() - set(MUTATING_ROUTES) == set(), (
        "routes modifiantes sans décision d'audit"
    )
    assert set(MUTATING_ROUTES) - _mutating_routes() == set(), (
        "décisions pour des routes qui n'existent plus"
    )


def test_exemptions_are_few_and_justified():
    exempt = {route: spec for route, spec in MUTATING_ROUTES.items() if spec[0] == EXEMPT}
    assert all(len(spec[1]) > 10 for spec in exempt.values())
    assert len(exempt) <= 8


def test_every_action_of_the_catalog_is_referenced_in_the_code():
    sources = "\n".join(
        path.read_text()
        for path in Path("app").rglob("*.py")
        if path.name != "enums.py" or "audit" not in str(path)
    )
    dead = [a.name for a in A if not re.search(rf"AuditAction\.{a.name}\b", sources)]
    assert dead == [], f"actions du catalogue jamais émises par le code : {dead}"


def test_declared_actions_exist_in_the_catalog():
    declared = {
        a
        for spec in {**MUTATING_ROUTES, **READS_THAT_ARE_AUDITED}.values()
        if spec[0] != EXEMPT
        for a in spec
    }
    assert declared <= set(A)


def test_every_catalog_action_is_attached_to_a_route_or_a_central_mechanism():
    declared = {
        a
        for spec in {**MUTATING_ROUTES, **READS_THAT_ARE_AUDITED}.values()
        if spec[0] != EXEMPT
        for a in spec
    }
    assert set(A) - declared - CENTRAL_ACTIONS == set()


def test_a_full_journey_produces_every_action_of_the_catalog(client, session, users, monkeypatch):
    """Preuve par l'exemple : un parcours complet de l'application émet CHAQUE action du catalogue."""
    monkeypatch.setattr("app.core.config.settings.MAX_LOGIN_ATTEMPTS", 2)
    boss, _second_admin = users.admin(), users.admin()
    ha = bearer(boss)
    email = "journey@example.com"

    # --- authentification
    client.post("/api/v1/auth/register", json=register_payload(email))
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )  # rejeu : vol
    fresh = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    client.post("/api/v1/auth/logout", json={"refresh_token": fresh["refresh_token"]})
    for _ in range(2):  # échecs puis verrou
        client.post("/api/v1/auth/login", json={"email": email, "password": "Wrong12345!"})

    # --- projets (propriétaire et administrateur)
    owner = users.user()
    hu = bearer(owner)
    project = client.post("/api/v1/projects", headers=hu, json={"name": "Alpha"}).json()
    client.patch(f"/api/v1/projects/{project['id']}", headers=hu, json={"description": "v2"})
    client.post(f"/api/v1/projects/{project['id']}/status", headers=hu, json={"status": "active"})
    client.delete(f"/api/v1/projects/{project['id']}", headers=hu)

    # --- création du premier administrateur (script, sans route)
    UserService.create_admin(
        session, email="root@example.com", password=PASSWORD, first_name="Root", last_name="Admin"
    )

    # --- accès refusé et consultation du journal
    client.get("/api/v1/admin/audit-logs", headers=hu)  # 403 : tracé
    client.get("/api/v1/admin/audit-logs", headers=ha)

    produced = set(actions(session))
    missing = {a.value for a in A} - produced
    assert missing == set(), f"actions jamais produites par le parcours complet : {sorted(missing)}"
