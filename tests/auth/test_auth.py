"""Authentification : inscription, connexion, jetons, verrouillage, sessions."""

from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from app.core.clock import utc_now
from app.core.security import create_access_token, hash_token
from app.modules.auth.models import UserSession
from app.modules.users.enums import UserStatus
from app.modules.users.models import User
from tests.helpers.auth import PASSWORD, bearer, register_payload

LOGIN = "/api/v1/auth/login"


def login(client, email, password=PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


# ---- Inscription ---------------------------------------------------------------------


def test_register_login_me_refresh_logout(client):
    """Parcours complet : inscription, connexion, /me, rafraîchissement, déconnexion."""
    r = client.post("/api/v1/auth/register", json=register_payload())
    assert r.status_code == 201
    assert r.json()["success"] is True
    assert r.json()["user"]["email"] == "test@example.com"
    assert "password" not in str(r.json())

    tokens = login(client, "test@example.com").json()
    assert tokens["token_type"] == "bearer"

    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "test@example.com"

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    new_refresh = refreshed.json()["refresh_token"]
    assert new_refresh != tokens["refresh_token"]

    assert (
        client.post("/api/v1/auth/logout", json={"refresh_token": new_refresh}).status_code == 200
    )
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401
    )


def test_register_creates_a_standard_user_never_an_admin(client):
    """Le rôle ne se choisit pas à l'inscription, même si le client l'envoie."""
    payload = {**register_payload(), "role": "admin", "status": "active"}
    r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "user"


def test_register_duplicate_email_returns_409_ignoring_case(client):
    assert client.post("/api/v1/auth/register", json=register_payload()).status_code == 201
    assert client.post("/api/v1/auth/register", json=register_payload()).status_code == 409
    shouting = register_payload(email="TEST@Example.COM")
    assert client.post("/api/v1/auth/register", json=shouting).status_code == 409


def test_register_normalizes_email_to_lowercase(client, session):
    client.post("/api/v1/auth/register", json=register_payload(email="Mixed.Case@Example.com"))
    stored = session.exec(select(User)).one()
    assert stored.email == "mixed.case@example.com"
    assert login(client, "MIXED.CASE@example.com").status_code == 200


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("short1", "trop court"),
        ("onlyletters", "sans chiffre"),
        ("12345678", "sans lettre"),
        ("a1" + "é" * 40, "plus de 72 octets (limite bcrypt)"),
    ],
)
def test_register_rejects_weak_passwords(client, password, reason):
    payload = {**register_payload(), "password": password}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 400, reason


@pytest.mark.parametrize(
    "override",
    [
        {"email": "not-an-email"},
        {"first_name": ""},
        {"last_name": ""},
        {"password": ""},
    ],
)
def test_register_rejects_invalid_fields(client, override):
    payload = {**register_payload(), **override}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 400


def test_register_stores_a_hashed_password_and_normalized_email(client, session):
    """Le mot de passe n'est jamais stocké en clair ; l'e-mail est enregistré en minuscules."""
    client.post("/api/v1/auth/register", json=register_payload(email="Mixed@Example.COM"))
    user = session.exec(select(User)).one()
    assert user.email == "mixed@example.com"
    assert user.password_hash != PASSWORD and user.password_hash.startswith("$2")


# ---- Connexion -----------------------------------------------------------------------


def test_unknown_email_and_wrong_password_are_indistinguishable(client, users):
    """Même code et même message : on ne peut pas savoir quels comptes existent."""
    account = users.user()
    wrong_password = login(client, account.email, "WrongPass123!")
    unknown_email = login(client, "ghost@example.com", "WrongPass123!")

    assert wrong_password.status_code == unknown_email.status_code == 401
    first, second = wrong_password.json()["error"], unknown_email.json()["error"]
    first.pop("request_id"), second.pop("request_id")  # seul élément propre à chaque requête
    assert first == second


def test_account_locks_after_repeated_failures_even_with_the_right_password(
    client, users, monkeypatch
):
    monkeypatch.setattr("app.core.config.settings.MAX_LOGIN_ATTEMPTS", 3)
    account = users.user()

    for _ in range(3):
        assert login(client, account.email, "WrongPass123!").status_code == 401

    locked = login(client, account.email)  # bon mot de passe, mais compte verrouillé
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0


def test_lock_expires_and_success_resets_the_counter(client, users, session, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.MAX_LOGIN_ATTEMPTS", 2)
    account = users.user()
    for _ in range(2):
        login(client, account.email, "WrongPass123!")

    account.locked_until = utc_now() - timedelta(seconds=1)  # verrou échu
    session.add(account)
    session.commit()

    assert login(client, account.email).status_code == 200
    session.refresh(account)
    assert account.failed_login_attempts == 0
    assert account.locked_until is None


def test_failures_below_the_threshold_do_not_lock(client, users):
    account = users.user()
    for _ in range(4):
        login(client, account.email, "WrongPass123!")
    assert login(client, account.email).status_code == 200


def test_blocked_account_gets_403_only_with_the_right_password(client, users):
    blocked = users.user(status=UserStatus.BLOCKED)
    assert login(client, blocked.email).status_code == 403
    assert login(client, blocked.email, "WrongPass123!").status_code == 401


def test_deleted_account_cannot_log_in(client, users):
    deleted = users.user(status=UserStatus.DELETED)
    assert login(client, deleted.email).status_code == 401


def test_login_is_rate_limited_per_ip(client, users, rate_limit, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_AUTH", "3/minute")
    account = users.user()

    statuses = [login(client, account.email, "WrongPass123!").status_code for _ in range(5)]

    assert statuses[:3] == [401, 401, 401]
    assert statuses[3:] == [429, 429]
    throttled = login(client, account.email)
    assert throttled.status_code == 429
    assert "Retry-After" in throttled.headers


def test_register_is_rate_limited_per_ip(client, rate_limit, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_REGISTER", "2/hour")
    codes = [
        client.post("/api/v1/auth/register", json=register_payload(f"u{i}@example.com")).status_code
        for i in range(3)
    ]
    assert codes == [201, 201, 429]


# ---- Jetons d'accès ------------------------------------------------------------------


def test_protected_route_requires_a_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_tampered_or_foreign_token_is_rejected(client, users):
    account = users.user()
    token = create_access_token(account.id, account.role)
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}x"}).status_code
        == 401
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code
        == 401
    )


def test_expired_access_token_is_rejected(client, users, monkeypatch):
    monkeypatch.setattr("app.core.security.ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    account = users.user()
    assert client.get("/api/v1/auth/me", headers=bearer(account)).status_code == 401


def test_token_of_a_deleted_user_is_rejected(client, users, session):
    account = users.user()
    headers = bearer(account)
    session.delete(account)
    session.commit()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_blocking_an_account_cuts_access_immediately_despite_a_valid_token(client, users, session):
    account = users.user()
    headers = bearer(account)
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    account.status = UserStatus.BLOCKED
    session.add(account)
    session.commit()

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 403


# ---- Refresh tokens ------------------------------------------------------------------


def test_refresh_token_is_stored_hashed_never_in_clear(client, users, session):
    account = users.user()
    tokens = login(client, account.email).json()

    stored = session.exec(select(UserSession)).one()
    assert stored.refresh_token_hash == hash_token(tokens["refresh_token"])
    assert tokens["refresh_token"] not in stored.model_dump_json()


def test_reusing_a_rotated_refresh_token_revokes_the_session(client, users, session):
    """Un jeton déjà tourné qui revient = vol probable : toute la session tombe."""
    account = users.user()
    first = login(client, account.email).json()["refresh_token"]
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first}).json()[
        "refresh_token"
    ]

    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert replay.status_code == 401

    # Le jeton légitime le plus récent est lui aussi invalidé : le voleur ET la victime
    # doivent se reconnecter.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": second}).status_code == 401
    assert session.exec(select(UserSession)).all() == []


def test_refresh_fails_and_drops_the_session_for_a_blocked_account(client, users, session):
    account = users.user()
    refresh = login(client, account.email).json()["refresh_token"]

    account.status = UserStatus.BLOCKED
    session.add(account)
    session.commit()

    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 401
    assert session.exec(select(UserSession)).all() == []


def test_expired_refresh_token_is_rejected_and_purged(client, users, session):
    account = users.user()
    refresh = login(client, account.email).json()["refresh_token"]
    stored = session.exec(select(UserSession)).one()
    stored.expires_at = utc_now() - timedelta(days=1)
    session.add(stored)
    session.commit()

    assert client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}).status_code == 401
    assert session.exec(select(UserSession)).all() == []


def test_unknown_refresh_token_is_rejected(client):
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"}).status_code == 401


def test_logout_unknown_token_returns_404(client):
    assert client.post("/api/v1/auth/logout", json={"refresh_token": "nope"}).status_code == 404


def test_sessions_per_user_are_capped_oldest_dropped_first(client, users, session, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.MAX_SESSIONS_PER_USER", 2)
    account = users.user()

    tokens = []
    for _ in range(3):
        tokens.append(login(client, account.email).json()["refresh_token"])
        # created_at identique à la microseconde près sur certains systèmes : on espace.
        for s in session.exec(select(UserSession)).all():
            s.created_at = (
                s.created_at - timedelta(seconds=5)
                if s.refresh_token_hash != hash_token(tokens[-1])
                else s.created_at
            )
            session.add(s)
        session.commit()

    assert len(session.exec(select(UserSession)).all()) == 2
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens[0]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens[2]}).status_code == 200


# ---- Changement de mot de passe ------------------------------------------------------


# ---- Interrupteur d'inscription ----------------------------------------------------------


def test_registration_can_be_closed_by_configuration(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.REGISTRATION_ENABLED", False)
    r = client.post("/api/v1/auth/register", json=register_payload())
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "registration_closed"
    assert r.json()["error"]["message"] == "Les inscriptions sont fermées"


def test_existing_accounts_can_still_log_in_when_registration_is_closed(client, users, monkeypatch):
    account = users.user()
    monkeypatch.setattr("app.core.config.settings.REGISTRATION_ENABLED", False)
    assert login(client, account.email).status_code == 200
