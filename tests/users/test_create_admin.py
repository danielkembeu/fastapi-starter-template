"""Création du premier administrateur : seule voie vers un rôle privilégié."""

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.modules.audit.enums import AuditAction
from app.modules.users.enums import UserRole
from app.modules.users.models import User
from app.modules.users.service import UserService
from scripts import create_admin
from tests.helpers.audit import only
from tests.helpers.auth import PASSWORD

ADMIN = {"email": "Boss@Example.com", "first_name": "Ada", "last_name": "Admin"}


def test_creates_an_administrator_with_a_hashed_password_and_an_audit_entry(session):
    admin = UserService.create_admin(session, password=PASSWORD, **ADMIN)

    assert admin.role is UserRole.ADMIN
    assert admin.email == "boss@example.com"  # normalisé
    assert admin.password_hash != PASSWORD
    entry = only(session, AuditAction.USER_ADMIN_CREATED)
    assert (entry.actor_type, entry.resource_id) == ("system", admin.id)


def test_an_existing_email_is_refused_whatever_its_case(session, users):
    existing = users.user(email="boss@example.com")
    with pytest.raises(HTTPException) as refused:
        UserService.create_admin(session, password=PASSWORD, **ADMIN)
    assert refused.value.status_code == 409
    assert session.exec(select(User)).all() == [existing]


@pytest.mark.parametrize("password", ["short1", "nodigitshere", "12345678"])
def test_the_password_policy_applies_to_administrators_too(session, password):
    with pytest.raises(HTTPException) as refused:
        UserService.create_admin(session, password=password, **ADMIN)
    assert refused.value.status_code == 400


def test_the_new_administrator_can_log_in_and_read_the_audit_journal(client, session):
    UserService.create_admin(session, password=PASSWORD, **ADMIN)
    token = client.post(
        "/api/v1/auth/login", json={"email": "boss@example.com", "password": PASSWORD}
    ).json()["access_token"]
    r = client.get("/api/v1/admin/audit-logs", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["total"] >= 1


def test_the_script_only_previews_without_confirm(session, monkeypatch, capsys):
    monkeypatch.setattr(create_admin.database, "engine", session.get_bind())
    code = create_admin.main(["--email", "x@example.com", "--first-name", "A", "--last-name", "B"])
    out = capsys.readouterr().out
    assert code == 0 and "Base visée" in out and "Aperçu" in out
    assert session.exec(select(User)).all() == []  # rien n'a été écrit


def test_the_script_writes_with_confirm(session, monkeypatch, capsys):
    monkeypatch.setattr(create_admin.database, "engine", session.get_bind())
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    code = create_admin.main(
        ["--email", "x@example.com", "--first-name", "A", "--last-name", "B", "--confirm"]
    )
    assert code == 0 and "Administrateur créé" in capsys.readouterr().out
    session.expire_all()
    assert [u.role for u in session.exec(select(User)).all()] == [UserRole.ADMIN]


def test_the_script_refuses_a_non_postgres_backend(monkeypatch, capsys):
    from app.core.config import DatabaseBackend

    monkeypatch.setattr("app.core.config.settings.DATABASE_BACKEND", DatabaseBackend.MONGODB)
    assert (
        create_admin.main(["--email", "x@example.com", "--first-name", "A", "--last-name", "B"])
        == 2
    )
