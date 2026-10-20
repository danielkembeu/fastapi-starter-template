"""Format d'erreur : code stable, message, détails, request_id — et aucune fuite."""

import pytest
from fastapi.testclient import TestClient

from app.core.errors import GENERIC_500_MESSAGE, AppError, ErrorCode
from app.server import server
from tests.helpers.auth import PASSWORD, bearer, register_payload

PROJECTS = "/api/v1/projects"


def error_of(response):
    body = response.json()
    assert set(body) == {"error"}, "une erreur n'a qu'une clé racine : « error »"
    return body["error"]


# ---- La forme ------------------------------------------------------------------------


def test_every_error_has_the_same_shape(client, users):
    error = error_of(
        client.get(f"{PROJECTS}/{'0' * 8}-0000-0000-0000-{'0' * 12}", headers=bearer(users.user()))
    )
    assert set(error) >= {"code", "message", "status", "request_id", "details"}
    assert (error["code"], error["status"]) == ("not_found", 404)
    assert error["details"] is None


def test_the_request_id_in_the_body_matches_the_response_header(client):
    r = client.get("/api/v1/nowhere", headers={"X-Request-ID": "trace-abcdef-0001"})
    assert error_of(r)["request_id"] == r.headers["X-Request-ID"] == "trace-abcdef-0001"


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("GET", "/api/v1/nowhere", 404, "not_found"),
        ("DELETE", "/api/v1/auth/me", 405, "method_not_allowed"),
        ("GET", "/api/v1/auth/me", 401, "unauthorized"),
    ],
)
def test_framework_errors_use_the_same_format_and_stable_codes(client, method, path, status, code):
    r = client.request(method, path)
    assert r.status_code == status
    error = error_of(r)
    assert error["code"] == code and error["status"] == status
    assert error["message"] and error["message"] not in {
        "Not Found",
        "Not authenticated",
    }  # en français


# ---- Validation ----------------------------------------------------------------------


def test_validation_errors_list_the_fields_in_details(client, users):
    r = client.post(PROJECTS, headers=bearer(users.user()), json={"name": ""})
    error = error_of(r)
    assert r.status_code == 400 and error["code"] == "validation_error"
    assert error["details"][0]["field"] == "body.name"
    assert error["details"][0]["code"] == "string_too_short"
    assert error["details"][0]["message"] == "Valeur trop courte"


def test_validation_never_echoes_the_submitted_values(client):
    """Un mot de passe mal formé ne doit pas revenir dans la réponse (ni `input`, ni `ctx`)."""
    secret = "tropcourt"
    r = client.post("/api/v1/auth/register", json={**register_payload(), "password": secret})
    assert r.status_code == 400
    assert secret not in r.text
    for detail in error_of(r)["details"]:
        assert set(detail) == {"field", "message", "code"}


def test_custom_validator_messages_are_kept_in_french(client):
    r = client.post("/api/v1/auth/register", json={**register_payload(), "password": "abcdefgh"})
    messages = [d["message"] for d in error_of(r)["details"]]
    assert any("lettre et un chiffre" in m for m in messages)


def test_a_malformed_json_body_is_a_clean_400(client, users):
    r = client.post(
        PROJECTS,
        headers={**bearer(users.user()), "Content-Type": "application/json"},
        content="{pas du json",
    )
    assert r.status_code == 400 and error_of(r)["code"] == "validation_error"


# ---- Erreurs métier ------------------------------------------------------------------


def test_business_errors_carry_their_own_stable_code(client, users):
    assert (
        error_of(
            client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": PASSWORD})
        )["code"]
        == "invalid_credentials"
    )
    register = client.post("/api/v1/auth/register", json=register_payload())
    assert register.status_code == 201
    again = client.post("/api/v1/auth/register", json=register_payload())
    assert (again.status_code, error_of(again)["code"]) == (409, "email_already_used")


def test_headers_of_an_error_are_preserved(client, users, monkeypatch):
    """`Retry-After` (verrou) et `WWW-Authenticate` (401) font partie du contrat."""
    monkeypatch.setattr("app.core.config.settings.MAX_LOGIN_ATTEMPTS", 1)
    account = users.user()
    client.post("/api/v1/auth/login", json={"email": account.email, "password": "Wrong12345!"})
    locked = client.post("/api/v1/auth/login", json={"email": account.email, "password": PASSWORD})
    assert locked.status_code == 429 and error_of(locked)["code"] == "account_locked"
    assert int(locked.headers["Retry-After"]) > 0

    unauthenticated = client.get("/api/v1/auth/me")
    assert unauthenticated.headers["WWW-Authenticate"] == "Bearer"


def test_app_error_is_an_http_exception_so_existing_handlers_still_work():
    from fastapi import HTTPException

    error = AppError(409, ErrorCode.CONFLICT, "Conflit", details=[{"field": "x", "message": "y"}])
    assert isinstance(error, HTTPException)
    assert (error.status_code, error.code, error.detail) == (409, "conflict", "Conflit")


# ---- Erreurs internes : aucune fuite -------------------------------------------------


def boom_app(users):
    from app.core.database import get_session

    def boom():
        raise RuntimeError("secret internal detail: db password is hunter2")
        yield  # pragma: no cover

    server.dependency_overrides[get_session] = boom
    return TestClient(server, raise_server_exceptions=False)


def test_an_unhandled_error_is_a_generic_500_with_a_request_id(users, session, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.ERROR_DEBUG", False)
    try:
        r = boom_app(users).get(
            PROJECTS, headers={**bearer(users.user()), "X-Request-ID": "trace-500-abcdef"}
        )
    finally:
        server.dependency_overrides.clear()

    error = error_of(r)
    assert r.status_code == 500
    assert (error["code"], error["message"]) == ("internal_error", GENERIC_500_MESSAGE)
    assert error["request_id"] == r.headers["X-Request-ID"] == "trace-500-abcdef"
    assert "debug" not in error
    assert "hunter2" not in r.text and "RuntimeError" not in r.text and "Traceback" not in r.text


def test_error_debug_shows_the_technical_detail_only_when_allowed(users, session, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.ERROR_DEBUG", True)
    try:
        r = boom_app(users).get(PROJECTS, headers=bearer(users.user()))
    finally:
        server.dependency_overrides.clear()
    debug = error_of(r)["debug"]
    assert debug["exception"] == "RuntimeError"
    assert any("hunter2" in line for line in debug["trace"]) or "hunter2" in debug["message"]


@pytest.mark.parametrize(
    ("environment", "explicit", "expected"),
    [
        ("local", None, True),
        ("ci", None, True),
        ("staging", None, False),
        ("production", None, False),
        ("staging", True, True),  # débogage ponctuel sur staging
        ("local", False, False),
    ],
)
def test_the_debug_policy_depends_on_the_environment(environment, explicit, expected):
    from app.core.config import Settings

    base = {
        "_env_file": None,
        "ENVIRONMENT": environment,
        "SECRET_JWT": "x7Kq9Zp2Lm4Vb8Nc1Rt6Yw3Hs5Df0GjA",  # gitleaks:allow (valeur factice de test)
        "DATABASE_URL": "postgresql://u:p@db.internal:5432/app",
        "EMAIL_BACKEND": "disabled",
        "CORS_ORIGINS": "https://app.example.com",
        "DOCS_USERNAME": "t",
        "DOCS_PASSWORD": "t",
        "ALLOW_REMOTE_DB_IN_LOCAL": True,
        "ERROR_DEBUG": explicit,
    }
    assert Settings(**base).expose_error_debug is expected
