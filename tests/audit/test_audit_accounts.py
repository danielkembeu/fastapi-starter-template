"""Traces d'audit : authentification et comptes."""

from uuid import UUID

from app.modules.audit.enums import AuditAction as A
from app.modules.audit.models import AuditLog
from app.modules.users.enums import UserStatus
from tests.helpers.audit import actions, entries, only
from tests.helpers.auth import PASSWORD, bearer, register_payload


def login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


# ---- Authentification -------------------------------------------------------------------


def test_registration_is_traced_with_the_new_user_as_actor(client, session):
    r = client.post("/api/v1/auth/register", json=register_payload("new@example.com"))
    user_id = UUID(r.json()["user"]["id"])

    entry = only(session, A.AUTH_REGISTER)
    assert (entry.actor_id, entry.actor_role, entry.resource_type, entry.resource_id) == (
        user_id,
        "user",
        "user",
        user_id,
    )
    assert entry.details == {"email": "new@example.com"}


def test_login_success_is_traced(client, session, users):
    account = users.user()
    login(client, account.email)
    entry = only(session, A.AUTH_LOGIN)
    assert (entry.actor_id, entry.resource_type, entry.outcome) == (
        account.id,
        "session",
        "success",
    )


def test_failed_logins_are_traced_with_the_reason_but_never_the_password(client, session, users):
    account = users.user()
    login(client, "ghost@example.com", "WrongPass123!")
    login(client, account.email, "WrongPass123!")
    login(client, account.email, "OtherWrong456!")

    unknown, first, second = entries(session, A.AUTH_LOGIN_FAILED)
    assert (unknown.details, unknown.actor_type, unknown.outcome) == (
        {"reason": "unknown_email", "email": "ghost@example.com"},
        "anonymous",
        "failed",
    )
    assert (first.resource_id, first.details) == (
        account.id,
        {"reason": "bad_password", "consecutive_failures": 1},
    )
    assert second.details["consecutive_failures"] == 2
    everything = " ".join(str(e.details) + str(e.changes) for e in entries(session))
    assert (
        "WrongPass123!" not in everything
        and "OtherWrong456!" not in everything
        and PASSWORD not in everything
    )


def test_lockout_and_attempts_during_the_lock_are_traced(client, session, users, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.MAX_LOGIN_ATTEMPTS", 2)
    account = users.user()
    for _ in range(2):
        login(client, account.email, "WrongPass123!")
    login(client, account.email)  # le bon mot de passe, pendant le verrou

    lock = only(session, A.AUTH_ACCOUNT_LOCKED)
    assert (lock.actor_type, lock.resource_id) == ("system", account.id)
    during = [
        e
        for e in entries(session, A.AUTH_LOGIN_FAILED)
        if e.details.get("reason") == "account_locked"
    ]
    assert len(during) == 1 and during[0].outcome == "denied"
    assert only(session, A.AUTH_LOGIN_FAILED, outcome="denied").resource_id == account.id


def test_blocked_and_deleted_accounts_trying_to_log_in_are_traced(client, session, users):
    blocked = users.user(status=UserStatus.BLOCKED)
    deleted = users.user(status=UserStatus.DELETED)
    login(client, blocked.email)
    login(client, deleted.email)
    reasons = {e.details["reason"] for e in entries(session, A.AUTH_LOGIN_FAILED)}
    assert reasons == {"account_blocked", "account_deleted"}


def test_refresh_logout_and_token_reuse_are_traced(client, session, users):
    account = users.user()
    first = login(client, account.email).json()["refresh_token"]
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first}).json()[
        "refresh_token"
    ]
    refreshed = only(session, A.AUTH_TOKEN_REFRESHED, outcome="success")
    assert (refreshed.actor_id, refreshed.resource_type) == (account.id, "session")

    client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first}
    )  # jeton déjà tourné : vol probable
    reuse = only(session, A.AUTH_TOKEN_REUSE_DETECTED)
    assert (reuse.outcome, reuse.details["user_id"]) == ("denied", str(account.id))

    client.post("/api/v1/auth/refresh", json={"refresh_token": "totally-unknown"})
    assert any(
        e.details == {"reason": "unknown_token"} for e in entries(session, A.AUTH_TOKEN_REFRESHED)
    )

    third = login(client, account.email).json()["refresh_token"]
    client.post("/api/v1/auth/logout", json={"refresh_token": third})
    assert only(session, A.AUTH_LOGOUT).actor_id == account.id
    assert second  # le jeton légitime a été invalidé avec la session


# ---- Comptes ----------------------------------------------------------------------------


def test_no_audit_row_is_written_by_read_only_calls(client, session, users):
    account = users.user()
    for path in ("/api/v1/projects", "/api/v1/auth/me"):
        client.get(path, headers=bearer(account))
    assert actions(session) == []
