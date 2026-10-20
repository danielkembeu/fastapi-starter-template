"""Service d'audit : construction, masquage des secrets, atomicité, robustesse."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, select

from app.core import database
from app.core.context import RequestContext, _current
from app.modules.audit.enums import ActorType, AuditAction, AuditOutcome
from app.modules.audit.models import AuditLog
from app.modules.audit.service import MAX_STRING_LENGTH, REDACTED, AuditService
from app.modules.projects.enums import ProjectStatus
from tests.helpers.audit import entries, only
from tests.helpers.factories import make_project


def test_log_records_actor_resource_and_outcome(session, users):
    admin = users.admin()
    project = make_project(session, admin, name="Alpha")

    AuditService.log(session, AuditAction.PROJECT_CREATED, actor=admin, resource=project)
    session.commit()

    entry = only(session, AuditAction.PROJECT_CREATED)
    assert (entry.actor_type, entry.actor_id, entry.actor_role) == ("user", admin.id, "admin")
    assert (entry.resource_type, entry.resource_id) == ("project", project.id)
    assert entry.outcome == "success"
    assert entry.created_at is not None


def test_without_actor_the_entry_is_anonymous_unless_system(session):
    AuditService.log(session, AuditAction.AUTH_LOGIN_FAILED, outcome=AuditOutcome.FAILED)
    AuditService.log(session, AuditAction.AUTH_TOKEN_REFRESHED, actor_type=ActorType.SYSTEM)
    session.commit()
    assert only(session, AuditAction.AUTH_LOGIN_FAILED).actor_type == "anonymous"
    assert only(session, AuditAction.AUTH_TOKEN_REFRESHED).actor_type == "system"


def test_resource_types_use_stable_names(session, users):
    account = users.user()
    project = make_project(session, account)
    other_id = uuid4()
    AuditService.log(session, AuditAction.PROJECT_CREATED, actor=account, resource=project)
    AuditService.log(session, AuditAction.AUTH_LOGIN, actor=account, resource=account)
    AuditService.log(
        session, AuditAction.AUTH_TOKEN_REFRESHED, resource_type="session", resource_id=other_id
    )
    session.commit()
    assert only(session, AuditAction.PROJECT_CREATED).resource_type == "project"
    assert only(session, AuditAction.AUTH_LOGIN).resource_type == "user"
    assert only(session, AuditAction.AUTH_TOKEN_REFRESHED).resource_id == other_id


def test_secrets_are_never_written_even_when_nested(session, users):
    """Un secret passé par mégarde dans `details` ou `changes` doit être masqué."""
    AuditService.log(
        session,
        AuditAction.AUTH_LOGIN,
        actor=users.user(),
        changes={"password_hash": {"from": "old-hash", "to": "new-hash"}},
        details={
            "password": "Secret123!",
            "nested": {"refresh_token": "abc", "confirmation_code": "123456", "ok": "visible"},
            "list": [{"access_token": "t"}],
            "Authorization": "Bearer xyz",
        },
    )
    session.commit()

    entry = only(session, AuditAction.AUTH_LOGIN)
    dump = str(entry.details) + str(entry.changes)
    for secret in ("Secret123!", "old-hash", "new-hash", "abc", "123456", "Bearer xyz", "'t'"):
        assert secret not in dump, secret
    assert entry.details["password"] == REDACTED
    assert entry.details["nested"]["ok"] == "visible"
    assert entry.details["list"][0]["access_token"] == REDACTED
    assert entry.changes["password_hash"] == REDACTED


def test_values_are_json_safe_and_long_strings_truncated(session, users):
    from datetime import UTC, datetime

    AuditService.log(
        session,
        AuditAction.PROJECT_STATUS_CHANGED,
        actor=users.user(),
        changes={"status": {"from": ProjectStatus.DRAFT, "to": ProjectStatus.ARCHIVED}},
        details={
            "id": uuid4(),
            "at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            "text": "x" * 5000,
        },
    )
    session.commit()
    entry = only(session, AuditAction.PROJECT_STATUS_CHANGED)
    assert entry.changes["status"] == {"from": "draft", "to": "archived"}
    assert isinstance(entry.details["id"], str)
    assert entry.details["at"].startswith("2026-01-02")
    assert len(entry.details["text"]) == MAX_STRING_LENGTH + 1


def test_diff_reports_only_what_changed(users):
    account = users.user()
    account_email = account.email
    before = AuditService.snapshot(account, ["first_name", "last_name", "email"])
    account.first_name = "Nouveau"
    account.email = "nouveau@example.com"
    assert AuditService.diff(before, account) == {
        "first_name": {"from": "Prénom", "to": "Nouveau"},
        "email": {"from": account_email, "to": "nouveau@example.com"},
    }
    assert AuditService.diff(AuditService.snapshot(account, ["last_name"]), account) == {}


def test_the_entry_is_atomic_with_the_operation(session, users):
    """Annuler la transaction annule aussi la trace : pas d'opération fantôme dans le journal."""
    AuditService.log(session, AuditAction.PROJECT_CREATED, actor=users.user())
    session.rollback()
    assert entries(session) == []


def test_log_does_not_commit_by_itself(session, users, engine):
    AuditService.log(session, AuditAction.PROJECT_CREATED, actor=users.user())
    with Session(engine) as other:  # une autre session ne voit rien tant qu'on n'a pas commité
        assert other.exec(select(AuditLog)).all() == []
    session.commit()
    with Session(engine) as other:
        assert len(other.exec(select(AuditLog)).all()) == 1


def test_detached_entry_survives_a_rollback_of_the_main_transaction(session, users):
    """Les refus lèvent une erreur HTTP (donc annulent la transaction) mais doivent rester tracés."""
    account = users.user()
    AuditService.log_detached(AuditAction.ACCESS_DENIED, actor=account, outcome=AuditOutcome.DENIED)
    session.rollback()
    assert only(session, AuditAction.ACCESS_DENIED).outcome == "denied"


def test_detached_write_never_raises(monkeypatch, caplog):
    broken = create_engine(
        "postgresql://nobody:nothing@127.0.0.1:1/none", connect_args={"connect_timeout": 1}
    )
    monkeypatch.setattr(database, "engine", broken)

    AuditService.log_detached(AuditAction.ACCESS_DENIED, outcome=AuditOutcome.DENIED)  # ne lève pas

    assert any("journal d'audit" in r.message.lower() for r in caplog.records)


def test_request_context_is_captured(session, users):
    token = _current.set(
        RequestContext(ip_address="10.1.2.3", user_agent="Pixel/8", request_id="req-12345678")
    )
    try:
        AuditService.log(session, AuditAction.AUTH_LOGIN, actor=users.user())
        session.commit()
    finally:
        _current.reset(token)
    entry = only(session, AuditAction.AUTH_LOGIN)
    assert (entry.ip_address, entry.user_agent, entry.request_id) == (
        "10.1.2.3",
        "Pixel/8",
        "req-12345678",
    )


def test_entries_outside_a_request_have_no_context(session, users):
    AuditService.log(session, AuditAction.AUTH_LOGIN, actor=users.user())
    session.commit()
    entry = only(session, AuditAction.AUTH_LOGIN)
    assert (entry.ip_address, entry.user_agent, entry.request_id) == (None, None, None)


@pytest.mark.parametrize("action", list(AuditAction))
def test_every_action_name_is_a_namespaced_string(action):
    assert "." in action.value and action.value == action.value.lower()
