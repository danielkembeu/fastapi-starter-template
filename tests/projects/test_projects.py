"""Module d'exemple `projects` : sert aussi de MODÈLE de tests pour une nouvelle ressource.

Pour chaque ressource, couvrir systématiquement : le cas nominal, le refus d'accès (403), l'isolation
entre utilisateurs, les entrées invalides (400), les transitions interdites (409), la pagination/les
filtres et la trace d'audit.
"""

from uuid import uuid4

import pytest

from app.modules.audit.enums import AuditAction as A
from app.modules.projects.enums import ProjectStatus
from tests.helpers.audit import actions, entries, only
from tests.helpers.auth import bearer
from tests.helpers.factories import make_project


def create(client, user, name="Alpha", **extra):
    return client.post("/api/v1/projects", headers=bearer(user), json={"name": name, **extra})


# ---- Création et lecture -------------------------------------------------------------


def test_create_a_project_owned_by_the_caller_in_draft(client, users):
    owner = users.user()
    r = create(client, owner, name="  Alpha  ", description="premier")

    assert r.status_code == 201
    body = r.json()
    assert (body["name"], body["description"], body["status"]) == ("Alpha", "premier", "draft")
    assert body["owner_id"] == str(owner.id)


def test_the_owner_cannot_be_chosen_by_the_client(client, users):
    owner, other = users.user(), users.user()
    r = client.post(
        "/api/v1/projects",
        headers=bearer(owner),
        json={"name": "X", "owner_id": str(other.id), "status": "archived"},
    )
    assert r.status_code == 201
    assert (r.json()["owner_id"], r.json()["status"]) == (str(owner.id), "draft")


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 121},
        {},
        {"name": "ok", "description": "d" * 2001},
    ],
)
def test_create_rejects_invalid_input(client, users, body):
    assert (
        client.post("/api/v1/projects", headers=bearer(users.user()), json=body).status_code == 400
    )


def test_administrators_supervise_but_do_not_create_projects(client, users):
    assert create(client, users.admin()).status_code == 403


def test_a_user_only_sees_their_own_projects(client, users, session):
    alice, bob = users.user(), users.user()
    mine = make_project(session, alice, name="Mine")
    theirs = make_project(session, bob, name="Theirs")

    listing = client.get("/api/v1/projects", headers=bearer(alice)).json()
    assert [p["id"] for p in listing["items"]] == [str(mine.id)]
    assert listing["total"] == 1
    # Le projet d'autrui n'est pas révélé : 404, pas 403.
    assert client.get(f"/api/v1/projects/{theirs.id}", headers=bearer(alice)).status_code == 404


def test_an_administrator_sees_everything(client, users, session):
    alice, bob, admin = users.user(), users.user(), users.admin()
    make_project(session, alice)
    theirs = make_project(session, bob)

    assert client.get("/api/v1/projects", headers=bearer(admin)).json()["total"] == 2
    assert client.get(f"/api/v1/projects/{theirs.id}", headers=bearer(admin)).status_code == 200


def test_unknown_project_is_404(client, users):
    assert (
        client.get(f"/api/v1/projects/{uuid4()}", headers=bearer(users.user())).status_code == 404
    )


def test_the_owner_filter_is_reserved_to_administrators(client, users, session):
    alice, admin = users.user(), users.admin()
    make_project(session, alice)
    assert (
        client.get(f"/api/v1/projects?owner_id={alice.id}", headers=bearer(alice)).status_code
        == 403
    )
    ok = client.get(f"/api/v1/projects?owner_id={alice.id}", headers=bearer(admin))
    assert ok.status_code == 200 and ok.json()["total"] == 1


# ---- Pagination, filtres, tri --------------------------------------------------------


def test_pagination_filters_and_sort(client, users, session):
    owner = users.user()
    for i in range(5):
        make_project(session, owner, name=f"Projet {i}")
    make_project(session, owner, name="Autre", status=ProjectStatus.ACTIVE)
    h = bearer(owner)

    page = client.get("/api/v1/projects?limit=2&offset=0&sort=name", headers=h).json()
    assert (page["total"], len(page["items"]), page["has_more"]) == (6, 2, True)
    assert [p["name"] for p in page["items"]] == ["Autre", "Projet 0"]

    assert client.get("/api/v1/projects?status=active", headers=h).json()["total"] == 1
    assert client.get("/api/v1/projects?q=projet", headers=h).json()["total"] == 5
    assert client.get("/api/v1/projects?q=%25", headers=h).json()["total"] == 0  # joker échappé


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-1", "sort=password", "status=x"]
)
def test_invalid_list_parameters_are_rejected(client, users, query):
    assert client.get(f"/api/v1/projects?{query}", headers=bearer(users.user())).status_code == 400


# ---- Modification --------------------------------------------------------------------


def test_patch_only_changes_provided_fields(client, users, session):
    owner = users.user()
    project = make_project(session, owner, name="Avant", description="garde-moi")

    r = client.patch(
        f"/api/v1/projects/{project.id}", headers=bearer(owner), json={"name": "Après"}
    )

    assert r.status_code == 200
    assert (r.json()["name"], r.json()["description"]) == ("Après", "garde-moi")


def test_a_null_name_is_refused_instead_of_crashing(client, users, session):
    owner = users.user()
    project = make_project(session, owner)
    r = client.patch(f"/api/v1/projects/{project.id}", headers=bearer(owner), json={"name": None})
    assert r.status_code == 400


def test_nobody_edits_someone_elses_project_but_an_administrator_can(client, users, session):
    alice, bob, admin = users.user(), users.user(), users.admin()
    project = make_project(session, alice)

    assert (
        client.patch(f"/api/v1/projects/{project.id}", headers=bearer(bob), json={"name": "Pirate"})
    ).status_code == 404
    assert (
        client.patch(
            f"/api/v1/projects/{project.id}", headers=bearer(admin), json={"name": "Modéré"}
        )
    ).status_code == 200


# ---- Machine à états -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "target", "code"),
    [
        (ProjectStatus.DRAFT, "active", 200),
        (ProjectStatus.DRAFT, "archived", 200),
        (ProjectStatus.ACTIVE, "archived", 200),
        (ProjectStatus.ACTIVE, "draft", 409),
        (ProjectStatus.ARCHIVED, "active", 409),
        (ProjectStatus.ARCHIVED, "draft", 409),
        (ProjectStatus.DRAFT, "draft", 409),
    ],
)
def test_status_transitions(client, users, session, start, target, code):
    owner = users.user()
    project = make_project(session, owner, status=start)
    r = client.post(
        f"/api/v1/projects/{project.id}/status", headers=bearer(owner), json={"status": target}
    )
    assert r.status_code == code


def test_an_archived_project_cannot_be_edited(client, users, session):
    owner = users.user()
    project = make_project(session, owner, status=ProjectStatus.ARCHIVED)
    r = client.patch(f"/api/v1/projects/{project.id}", headers=bearer(owner), json={"name": "Non"})
    assert r.status_code == 409


# ---- Suppression ---------------------------------------------------------------------


def test_owner_and_administrator_can_delete_others_cannot(client, users, session):
    alice, bob, admin = users.user(), users.user(), users.admin()
    mine = make_project(session, alice)
    other = make_project(session, alice)

    assert client.delete(f"/api/v1/projects/{mine.id}", headers=bearer(bob)).status_code == 404
    assert client.delete(f"/api/v1/projects/{mine.id}", headers=bearer(alice)).status_code == 204
    assert client.get(f"/api/v1/projects/{mine.id}", headers=bearer(alice)).status_code == 404
    assert client.delete(f"/api/v1/projects/{other.id}", headers=bearer(admin)).status_code == 204


# ---- Audit ---------------------------------------------------------------------------


def test_audit_entries_name_the_actor_and_record_changes(client, users, session):
    owner = users.user()
    h = bearer(owner)
    project_id = create(client, owner, name="Trace").json()["id"]
    client.patch(f"/api/v1/projects/{project_id}", headers=h, json={"name": "Trace 2"})
    client.post(f"/api/v1/projects/{project_id}/status", headers=h, json={"status": "active"})
    client.delete(f"/api/v1/projects/{project_id}", headers=h)

    assert actions(session) == [
        A.PROJECT_CREATED.value,
        A.PROJECT_UPDATED.value,
        A.PROJECT_STATUS_CHANGED.value,
        A.PROJECT_DELETED.value,
    ]
    assert only(session, A.PROJECT_UPDATED).changes == {"name": {"from": "Trace", "to": "Trace 2"}}
    assert only(session, A.PROJECT_STATUS_CHANGED).changes["status"] == {
        "from": "draft",
        "to": "active",
    }
    assert only(session, A.PROJECT_CREATED).actor_id == owner.id
    assert only(session, A.PROJECT_DELETED).details["name"] == "Trace 2"


def test_refused_and_read_only_calls_leave_no_success_trace(client, users, session):
    alice, bob = users.user(), users.user()
    project = make_project(session, alice)

    client.get("/api/v1/projects", headers=bearer(alice))
    client.patch(f"/api/v1/projects/{project.id}", headers=bearer(bob), json={"name": "Pirate"})
    client.post("/api/v1/projects", headers=bearer(alice), json={"name": ""})  # invalide

    assert entries(session, A.PROJECT_CREATED) == []
    assert entries(session, A.PROJECT_UPDATED) == []


def test_an_update_that_changes_nothing_leaves_no_trace(client, users, session):
    owner = users.user()
    project = make_project(session, owner, name="Stable")
    client.patch(f"/api/v1/projects/{project.id}", headers=bearer(owner), json={"name": "Stable"})
    assert entries(session, A.PROJECT_UPDATED) == []
