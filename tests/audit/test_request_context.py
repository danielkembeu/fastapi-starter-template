"""Chaque requête reçoit un identifiant, et l'IP / le navigateur / l'identifiant atteignent le journal."""

from app.modules.audit.enums import AuditAction
from app.server import server
from tests.helpers.audit import only
from tests.helpers.auth import PASSWORD, bearer


def login(client, email, **headers):
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}, headers=headers
    )


def test_every_response_carries_a_request_id(client):
    first, second = client.get("/health/live"), client.get("/health/live")
    ids = {first.headers["x-request-id"], second.headers["x-request-id"]}
    assert len(ids) == 2 and all(len(i) >= 16 for i in ids)


def test_error_responses_carry_it_too(client):
    assert client.get("/api/does-not-exist").headers["x-request-id"]
    assert client.get("/api/v1/auth/me").headers["x-request-id"]  # 401


def test_a_sane_client_supplied_id_is_kept_so_logs_can_be_correlated(client):
    r = client.get("/health/live", headers={"X-Request-ID": "mobile-app-abc12345"})
    assert r.headers["x-request-id"] == "mobile-app-abc12345"


def test_a_malformed_client_id_is_replaced(client):
    for hostile in ("short", "with spaces in it!", "x" * 200, "id;drop table audit_logs"):
        r = client.get("/health/live", headers={"X-Request-ID": hostile})
        assert r.headers["x-request-id"] != hostile


def test_the_journal_records_ip_user_agent_and_request_id(client, session, users):
    account = users.user()

    r = login(
        client,
        account.email,
        **{"User-Agent": "Mobile-App/2.1 (Android 14)", "X-Request-ID": "trace-0123456789"},
    )

    assert r.status_code == 200
    entry = only(session, AuditAction.AUTH_LOGIN)
    assert entry.request_id == "trace-0123456789"
    assert entry.user_agent == "Mobile-App/2.1 (Android 14)"
    assert entry.ip_address == "testclient"
    assert entry.actor_id == account.id


def test_one_request_one_id_across_all_the_entries_it_creates(client, session, users, monkeypatch):
    """Une requête qui déclenche plusieurs entrées (échec + verrouillage) les relie par un même identifiant."""
    from sqlmodel import select

    from app.modules.audit.models import AuditLog

    monkeypatch.setattr("app.core.config.settings.MAX_LOGIN_ATTEMPTS", 1)
    account = users.user()
    r = client.post(
        "/api/v1/auth/login",
        headers={"X-Request-ID": "lockout-flow-0001"},
        json={"email": account.email, "password": "Wrong12345!"},
    )
    assert r.status_code == 401

    rows = session.exec(select(AuditLog).where(AuditLog.request_id == "lockout-flow-0001")).all()
    assert {row.action for row in rows} >= {"auth.login_failed", "auth.account_locked"}


def test_the_user_agent_is_truncated(client, session, users):
    account = users.user()
    login(client, account.email, **{"User-Agent": "A" * 600})
    assert len(only(session, AuditAction.AUTH_LOGIN).user_agent) <= 255


def test_request_id_is_exposed_to_browsers_through_cors(client):
    r = client.options(
        "/api/v1/auth/me",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    exposed = client.get("/health/live", headers={"Origin": "http://localhost:3000"}).headers.get(
        "access-control-expose-headers", ""
    )
    assert "X-Request-ID" in exposed and "Retry-After" in exposed
    assert r.status_code in (200, 400)


def test_the_context_does_not_leak_between_requests(client, session, users):
    a, b = users.user(), users.user()
    login(client, a.email, **{"User-Agent": "Agent-A", "X-Request-ID": "req-aaaaaaaa"})
    login(client, b.email, **{"User-Agent": "Agent-B", "X-Request-ID": "req-bbbbbbbb"})
    from tests.helpers.audit import entries

    by_actor = {e.actor_id: e for e in entries(session, AuditAction.AUTH_LOGIN)}
    assert by_actor[a.id].user_agent == "Agent-A" and by_actor[a.id].request_id == "req-aaaaaaaa"
    assert by_actor[b.id].user_agent == "Agent-B" and by_actor[b.id].request_id == "req-bbbbbbbb"


def test_middleware_is_registered_outermost():
    from app.core.context import RequestContextMiddleware

    assert server.user_middleware[0].cls is RequestContextMiddleware
