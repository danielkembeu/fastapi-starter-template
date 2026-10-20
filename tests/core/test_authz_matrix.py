"""Matrice rôle × endpoint.

La table EXPECTED_ACCESS dit, pour chaque route, quels rôles y ont accès. Le balayage envoie une
vraie requête avec chaque identité et vérifie le refus (401 sans jeton, 403 « Permissions
insuffisantes » pour un rôle non autorisé) ou le passage de la garde. C'est ce qui garantit
qu'une modification future n'ouvrira pas discrètement une route d'administration à tous.

À chaque nouvelle route : l'ajouter ici (le test `test_every_route_is_declared…` l'exige).
"""

import pytest
from fastapi.routing import APIRoute

from app.core.authz import FORBIDDEN_MESSAGE, ROLE_PERMISSIONS, Permission
from app.modules.users.enums import UserRole
from app.server import server
from tests.helpers.auth import bearer

U, A = "user", "admin"
EVERYONE = frozenset({U, A})
PUBLIC = "public"

EXPECTED_ACCESS: dict[tuple[str, str], frozenset[str] | str] = {
    # --- Sondes de santé (publiques : un orchestrateur ne sait pas porter de jeton)
    ("GET", "/health/live"): PUBLIC,
    ("GET", "/health/startup"): PUBLIC,
    ("GET", "/health/ready"): PUBLIC,
    # --- Authentification
    ("POST", "/api/v1/auth/register"): PUBLIC,
    ("POST", "/api/v1/auth/login"): PUBLIC,
    ("POST", "/api/v1/auth/token"): PUBLIC,
    ("POST", "/api/v1/auth/refresh"): PUBLIC,
    ("POST", "/api/v1/auth/logout"): PUBLIC,
    ("GET", "/api/v1/auth/me"): EVERYONE,
    # --- Projets (exemple)
    ("GET", "/api/v1/projects"): EVERYONE,
    ("POST", "/api/v1/projects"): {U},
    ("GET", "/api/v1/projects/{project_id}"): EVERYONE,
    ("PATCH", "/api/v1/projects/{project_id}"): EVERYONE,
    ("POST", "/api/v1/projects/{project_id}/status"): EVERYONE,
    ("DELETE", "/api/v1/projects/{project_id}"): EVERYONE,
    # --- Supervision
    ("GET", "/api/v1/admin/audit-logs"): {A},
}

# Hors périmètre de la matrice : documentation (testée dans test_docs.py) et favicon.
NOT_API = {"/docs", "/redoc", "/openapi.json", "/favicon.ico"}
SOME_UUID = "00000000-0000-0000-0000-000000000001"
PLACEHOLDERS = ("{project_id}",)


def app_routes() -> set[tuple[str, str]]:
    found = set()
    for route in server.routes:
        if isinstance(route, APIRoute) and route.path not in NOT_API:
            for method in route.methods - {"HEAD", "OPTIONS"}:
                found.add((method, route.path))
    return found


def test_every_route_is_declared_in_the_access_table():
    """Ajouter une route sans décider qui y a accès fait échouer ce test."""
    declared = set(EXPECTED_ACCESS)
    actual = app_routes()
    assert actual - declared == set(), "routes sans règle d'accès déclarée"
    assert declared - actual == set(), "règles d'accès pour des routes qui n'existent plus"


@pytest.fixture(name="identities")
def identities_fixture(users):
    return {U: users.user(), A: users.admin()}


def call(client, method, path, headers=None):
    url = path
    for placeholder in PLACEHOLDERS:
        url = url.replace(placeholder, SOME_UUID)
    kwargs = {"headers": headers or {}}
    if method in {"POST", "PATCH", "PUT"}:
        kwargs["json"] = {}
    return client.request(method, url, **kwargs)


def _protected_routes():
    return sorted((k, v) for k, v in EXPECTED_ACCESS.items() if v != PUBLIC)


@pytest.mark.parametrize(
    ("route", "roles"), _protected_routes(), ids=lambda v: str(v) if isinstance(v, tuple) else ""
)
def test_access_matrix(client, identities, route, roles):
    method, path = route

    anonymous = call(client, method, path)
    assert anonymous.status_code == 401, f"{method} {path} accessible sans jeton"
    assert anonymous.json()["error"]["code"] == "unauthorized"

    for role, user in identities.items():
        response = call(client, method, path, bearer(user))
        denied_by_role = (
            response.status_code == 403
            and response.json().get("error", {}).get("message") == FORBIDDEN_MESSAGE
        )
        if role in roles:
            assert response.status_code != 401 and not denied_by_role, (
                f"{role} devrait avoir accès à {method} {path} "
                f"(reçu {response.status_code} {response.text[:120]})"
            )
        else:
            assert denied_by_role, (
                f"{role} ne devrait PAS accéder à {method} {path} "
                f"(reçu {response.status_code} {response.text[:120]})"
            )


def _public_routes():
    return sorted(k for k, v in EXPECTED_ACCESS.items() if v == PUBLIC)


@pytest.mark.parametrize("route", _public_routes(), ids=lambda r: f"{r[0]} {r[1]}")
def test_public_routes_do_not_require_a_bearer_token(client, route):
    method, path = route
    response = call(client, method, path)
    assert response.json().get("error", {}).get("code") != "unauthorized"


# ---- La matrice de permissions elle-même ---------------------------------------------


def test_every_permission_is_granted_to_somebody():
    granted = set().union(*ROLE_PERMISSIONS.values())
    assert set(Permission) - granted == set(), "permission morte : accordée à aucun rôle"


def test_every_role_has_a_permission_set():
    assert set(ROLE_PERMISSIONS) == set(UserRole)


def test_standard_users_hold_no_administration_permission():
    admin_only = {Permission.AUDIT_READ}
    assert not (admin_only & ROLE_PERMISSIONS[UserRole.USER])


def test_scoped_read_all_permissions_belong_to_admin_only():
    for permission in Permission:
        if permission.value.endswith(":all"):
            holders = {role for role, perms in ROLE_PERMISSIONS.items() if permission in perms}
            assert holders == {UserRole.ADMIN}, permission
