"""Logs : format et niveau selon l'environnement, traces maîtrisées, secrets jamais écrits."""

import io
import json
import logging

import pytest

from app.core.config import Settings
from app.core.logging import JsonFormatter, TextFormatter, build_formatter
from tests.helpers.auth import PASSWORD, bearer, register_payload

SECRET_JWT = "x7Kq9Zp2Lm4Vb8Nc1Rt6Yw3Hs5Df0GjA"  # gitleaks:allow (valeur factice de test)


def settings_for(environment: str, **overrides) -> Settings:
    base = {
        "_env_file": None,
        "ENVIRONMENT": environment,
        "SECRET_JWT": SECRET_JWT,
        "DATABASE_URL": "postgresql://u:p@db.internal:5432/app",
        "EMAIL_BACKEND": "disabled",
        "CORS_ORIGINS": "https://app.example.com",
        "DOCS_USERNAME": "t",
        "DOCS_PASSWORD": "t",
        "ALLOW_REMOTE_DB_IN_LOCAL": True,
    }
    return Settings(**{**base, **overrides})


def record_with_exception(message: str = "boom") -> logging.LogRecord:
    try:
        raise ValueError(message)
    except ValueError:
        import sys

        return logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "échec", None, sys.exc_info()
        )


def emit(formatter: logging.Formatter, level: int, message: str, **extra) -> str:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger = logging.getLogger(f"test.fmt.{id(stream)}")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.log(level, message, extra=extra)
    return stream.getvalue().strip()


# ---- Politique par environnement -----------------------------------------------------


@pytest.mark.parametrize(
    ("environment", "level", "json_format", "stacktraces"),
    [
        ("local", "DEBUG", False, True),
        ("ci", "INFO", False, True),
        ("staging", "INFO", True, True),
        ("production", "INFO", True, False),  # en production, Sentry porte les traces
    ],
)
def test_defaults_by_environment(environment, level, json_format, stacktraces):
    settings = settings_for(environment)
    assert settings.log_level_name == level
    assert settings.log_json is json_format
    assert settings.log_stacktraces is stacktraces
    assert isinstance(build_formatter(settings), JsonFormatter if json_format else TextFormatter)


def test_every_default_can_be_overridden():
    settings = settings_for(
        "production", LOG_LEVEL="warning", LOG_FORMAT="text", LOG_STACKTRACES="true"
    )
    assert (settings.log_level_name, settings.log_json, settings.log_stacktraces) == (
        "WARNING",
        False,
        True,
    )
    assert settings_for("local", LOG_FORMAT="json").log_json is True


def test_an_unknown_log_level_prevents_startup():
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        settings_for("local", LOG_LEVEL="bavard")


def test_error_debug_true_is_refused_in_production():
    with pytest.raises(ValueError, match="ERROR_DEBUG"):
        settings_for("production", ERROR_DEBUG="true")
    assert settings_for("staging", ERROR_DEBUG="true").expose_error_debug is True


# ---- Format JSON ---------------------------------------------------------------------


def test_json_line_carries_the_standard_fields_and_the_extras():
    formatter = JsonFormatter(stacktraces=True, service="api", environment="staging")
    line = json.loads(
        emit(
            formatter, logging.INFO, "Connexion réussie", event="auth.login.succeeded", user_id="u1"
        )
    )
    assert line["level"] == "INFO" and line["message"] == "Connexion réussie"
    assert (line["service"], line["env"]) == ("api", "staging")
    assert (line["event"], line["user_id"]) == ("auth.login.succeeded", "u1")
    assert line["ts"].endswith("+00:00")  # UTC


def test_json_drops_empty_extras_and_stringifies_unserializable_values():
    formatter = JsonFormatter(stacktraces=True)
    line = json.loads(emit(formatter, logging.INFO, "x", user_id=None, objet=object()))
    assert "user_id" not in line and isinstance(line["objet"], str)


def test_sensitive_keys_are_masked_in_every_format():
    for formatter in (JsonFormatter(stacktraces=True), TextFormatter(stacktraces=True)):
        out = emit(
            formatter,
            logging.INFO,
            "contexte",
            password="hunter2",
            nested={"refresh_token": "abc.def", "ok": "visible"},
            Authorization="Bearer xyz",
        )
        assert "hunter2" not in out and "abc.def" not in out and "Bearer xyz" not in out
        assert "[masqué]" in out and "visible" in out


# ---- Traces d'appels -----------------------------------------------------------------


def test_stacktraces_are_included_when_allowed():
    out = JsonFormatter(stacktraces=True).format(record_with_exception())
    assert "Traceback" in json.loads(out)["exception"]


def test_without_stacktraces_only_the_exception_type_is_logged():
    """Le message d'une exception peut contenir des données (e-mail, identifiant) : en production, seul le type sort."""
    record = record_with_exception("mot de passe de jean@example.com")
    entry = json.loads(JsonFormatter(stacktraces=False).format(record))
    assert entry["exception"] == "ValueError"
    assert "jean@example.com" not in json.dumps(entry)
    text = TextFormatter(stacktraces=False).format(record)
    assert "jean@example.com" not in text and "ValueError" in text


# ---- Journal d'accès -----------------------------------------------------------------


def access_records(caplog):
    return [r for r in caplog.records if getattr(r, "event", None) == "http.request"]


def test_one_access_line_per_request_with_the_outcome(client, users, caplog):
    caplog.set_level(logging.DEBUG)
    client.get("/api/v1/projects", headers=bearer(users.user()))
    (record,) = access_records(caplog)
    assert record.levelno == logging.INFO
    assert (record.method, record.path, record.status) == ("GET", "/api/v1/projects", 200)
    assert record.duration_ms >= 0 and record.user_id and record.request_id


def test_levels_follow_the_outcome(client, caplog):
    caplog.set_level(logging.DEBUG)
    client.get("/api/v1/nowhere")  # 404 : erreur du client
    client.get("/api/v1/auth/me")  # 401
    assert [r.levelno for r in access_records(caplog)] == [logging.WARNING, logging.WARNING]


def test_a_server_error_is_logged_at_error_level(users, session, caplog):
    from fastapi.testclient import TestClient

    from app.core.database import get_session
    from app.server import server

    def boom():
        raise RuntimeError("panne")
        yield  # pragma: no cover

    server.dependency_overrides[get_session] = boom
    caplog.set_level(logging.DEBUG)
    try:
        TestClient(server, raise_server_exceptions=False).get(
            "/api/v1/projects", headers=bearer(users.user())
        )
    finally:
        server.dependency_overrides.clear()
    (record,) = access_records(caplog)
    assert (record.status, record.levelno) == (500, logging.ERROR)
    unhandled = [r for r in caplog.records if getattr(r, "event", None) == "error.unhandled"]
    assert unhandled and unhandled[0].exception == "RuntimeError"
    assert (
        unhandled[0].request_id == record.request_id
    )  # même identifiant : on retrouve toute l'histoire


def test_health_probes_do_not_flood_the_access_log(client, caplog):
    caplog.set_level(logging.DEBUG)
    client.get("/health/live")
    assert access_records(caplog) == []


def test_the_query_string_is_never_logged(client, caplog):
    """Elle peut contenir un jeton ou un terme de recherche personnel."""
    caplog.set_level(logging.DEBUG)
    client.get("/api/v1/projects?q=jean.dupont&access_token=SECRETTOKEN")
    assert "SECRETTOKEN" not in caplog.text and "jean.dupont" not in caplog.text


def test_the_request_id_is_the_same_in_the_log_and_the_response(client, caplog):
    caplog.set_level(logging.DEBUG)
    r = client.get("/api/v1/nowhere", headers={"X-Request-ID": "trace-log-0001"})
    assert r.headers["X-Request-ID"] == "trace-log-0001"
    assert access_records(caplog)[0].request_id == "trace-log-0001"


# ---- Événements métier et absence de secrets -----------------------------------------


def events(caplog):
    return {r.event: r for r in caplog.records if hasattr(r, "event")}


def test_authentication_events_are_logged_without_personal_data(client, users, caplog):
    caplog.set_level(logging.DEBUG)
    account = users.user()
    client.post("/api/v1/auth/login", json={"email": account.email, "password": PASSWORD})
    client.post("/api/v1/auth/login", json={"email": account.email, "password": "Wrong12345!"})

    logged = events(caplog)
    assert logged["auth.login.succeeded"].levelno == logging.INFO
    refused = logged["auth.login.failed"]
    assert (refused.levelno, refused.reason) == (logging.WARNING, "bad_password")
    assert account.email not in caplog.text
    assert PASSWORD not in caplog.text and "Wrong12345!" not in caplog.text


def test_account_lock_and_registration_are_logged(client, caplog, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.MAX_LOGIN_ATTEMPTS", 1)
    caplog.set_level(logging.DEBUG)
    client.post("/api/v1/auth/register", json=register_payload())
    client.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "Wrong12345!"})
    logged = events(caplog)
    assert logged["auth.register.succeeded"].levelno == logging.INFO
    assert logged["auth.account.locked"].levelno == logging.WARNING
    assert "test@example.com" not in caplog.text


def test_a_rejected_registration_does_not_log_the_submitted_password(client, caplog):
    caplog.set_level(logging.DEBUG)
    client.post("/api/v1/auth/register", json={**register_payload(), "password": "court1"})
    assert "court1" not in caplog.text
