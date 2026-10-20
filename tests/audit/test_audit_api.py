"""Consultation du journal : accès, filtres, pagination, absence de route de modification."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute

from app.core.clock import utc_now
from app.modules.audit.enums import AuditAction, AuditOutcome
from app.modules.audit.models import AuditLog
from app.modules.audit.service import AuditService
from app.server import server
from tests.helpers.audit import entries, only
from tests.helpers.auth import bearer

URL = "/api/v1/admin/audit-logs"


def add(session, action, **kwargs):
    entry = AuditService.build(action, **kwargs)
    session.add(entry)
    session.commit()
    return entry


def test_only_admins_can_read_the_journal(client, users):
    for user in (users.user(), users.user()):
        assert client.get(URL, headers=bearer(user)).status_code == 403
    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=bearer(users.admin())).status_code == 200


def test_the_list_is_newest_first_and_paginated(client, session, users):
    admin = users.admin()
    for i in range(5):
        entry = AuditService.build(AuditAction.PROJECT_CREATED, details={"n": i})
        entry.created_at = datetime(2026, 1, 1, 12, 0, i)  # noqa: DTZ001 — colonne UTC naïve
        session.add(entry)
    session.commit()
    h = bearer(admin)

    page = client.get(f"{URL}?limit=2&action=project.created", headers=h).json()
    assert [e["details"]["n"] for e in page["items"]] == [4, 3]
    assert (page["total"], page["has_more"]) == (5, True)
    oldest_first = client.get(
        f"{URL}?sort=created_at&limit=1&action=project.created", headers=h
    ).json()
    assert oldest_first["items"][0]["details"]["n"] == 0


def test_filter_by_actor_action_outcome_and_resource(client, session, users):
    admin, alice, bob = users.admin(), users.user(), users.user()
    order_id = uuid4()
    add(
        session,
        AuditAction.PROJECT_CREATED,
        actor=alice,
        resource_type="project",
        resource_id=order_id,
    )
    add(
        session,
        AuditAction.PROJECT_DELETED,
        actor=alice,
        resource_type="project",
        resource_id=order_id,
    )
    add(
        session,
        AuditAction.PROJECT_CREATED,
        actor=bob,
        resource_type="project",
        resource_id=uuid4(),
    )
    add(session, AuditAction.AUTH_LOGIN_FAILED, outcome=AuditOutcome.FAILED)
    h = bearer(admin)

    def total(query):
        return client.get(f"{URL}?{query}", headers=h).json()["total"]

    assert total(f"actor_id={alice.id}") == 2
    assert total("action=project.created") == 2
    assert total("outcome=failed") == 1
    history = client.get(
        f"{URL}?resource_type=project&resource_id={order_id}&sort=created_at", headers=h
    ).json()
    assert [e["action"] for e in history["items"]] == ["project.created", "project.deleted"]
    assert total(f"actor_id={alice.id}&action=project.deleted") == 1


def test_filter_by_date_range_and_request_id(client, session, users):
    h = bearer(users.admin())
    old = AuditService.build(AuditAction.PROJECT_CREATED)
    old.created_at = datetime(2020, 1, 1)  # noqa: DTZ001 — colonne UTC naïve
    old.request_id = "old-request-1"
    session.add(old)
    session.commit()
    add(session, AuditAction.PROJECT_CREATED)

    assert (
        client.get(f"{URL}?action=project.created&created_to=2021-01-01", headers=h).json()["total"]
        == 1
    )
    recent = (utc_now() - timedelta(days=1)).isoformat()
    assert (
        client.get(f"{URL}?action=project.created&created_from={recent}", headers=h).json()["total"]
        == 1
    )
    assert client.get(f"{URL}?request_id=old-request-1", headers=h).json()["total"] == 1
    assert (
        client.get(f"{URL}?created_from=2030-01-01&created_to=2020-01-01", headers=h).status_code
        == 400
    )


@pytest.mark.parametrize(
    "query",
    ["action=not.an.action", "outcome=maybe", "actor_id=nope", "sort=password", "limit=500"],
)
def test_invalid_filters_are_rejected(client, users, query):
    assert client.get(f"{URL}?{query}", headers=bearer(users.admin())).status_code == 400


def test_the_response_exposes_the_full_trail(client, session, users):
    admin, account = users.admin(), users.user()
    add(
        session,
        AuditAction.PROJECT_UPDATED,
        actor=admin,
        resource_type="project",
        resource_id=uuid4(),
        changes={"price": {"from": 1000, "to": 1500}},
        details={"why": "test"},
    )
    item = client.get(f"{URL}?action=project.updated", headers=bearer(admin)).json()["items"][0]
    assert item["changes"] == {"price": {"from": 1000, "to": 1500}}
    assert (item["actor_role"], item["actor_type"], item["outcome"]) == ("admin", "user", "success")
    assert {
        "id",
        "created_at",
        "resource_type",
        "resource_id",
        "ip_address",
        "user_agent",
        "request_id",
    } <= item.keys()
    assert account.email not in str(item)


def test_reading_the_journal_is_itself_journalled(client, session, users):
    admin = users.admin()
    client.get(f"{URL}?outcome=denied&action=access.denied", headers=bearer(admin))

    entry = only(session, AuditAction.AUDIT_VIEWED)
    assert entry.actor_id == admin.id
    assert entry.details == {"outcome": "denied", "action": "access.denied"}


def test_a_denied_attempt_to_read_the_journal_is_recorded(client, session, users):
    intruder = users.user()
    assert client.get(URL, headers=bearer(intruder)).status_code == 403

    entry = only(session, AuditAction.ACCESS_DENIED)
    assert (entry.actor_id, entry.outcome) == (intruder.id, "denied")
    assert entry.details["path"] == URL and entry.details["method"] == "GET"


def test_there_is_no_way_to_modify_or_delete_an_entry_through_the_api(client, session, users):
    methods = {
        method
        for route in server.routes
        if isinstance(route, APIRoute) and route.path.startswith(URL)
        for method in route.methods
    }
    assert methods <= {"GET", "HEAD", "OPTIONS"}

    entry = add(session, AuditAction.PROJECT_CREATED)
    h = bearer(users.admin())
    for method in ("put", "patch", "delete", "post"):
        response = getattr(client, method)(f"{URL}/{entry.id}", headers=h)
        assert response.status_code in (404, 405), method
    assert session.get(AuditLog, entry.id) is not None


def test_denied_attempts_by_anonymous_users_are_not_flooding_the_journal(client, session):
    for _ in range(5):
        client.get(URL)  # 401, aucun acteur identifiable
    assert entries(session, AuditAction.ACCESS_DENIED) == []
