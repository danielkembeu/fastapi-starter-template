"""Briques de pagination, tri et filtres."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    PageParams,
    apply_date_range,
    apply_sort,
    like_pattern,
    paginate,
)
from app.modules.projects.models import Project
from tests.helpers.factories import make_project


def seed(session, n):
    owner = _owner(session)
    for i in range(n):
        make_project(session, owner, name=f"cat-{i:02d}")


def _owner(session):
    from tests.helpers.auth import TestUsers

    return TestUsers(session).user()


def test_paginate_reports_total_and_has_more(session):
    seed(session, 5)
    stmt = apply_sort(select(Project), "name", {"name": Project.name}, Project.id)

    first = paginate(session, stmt, PageParams(limit=2, offset=0))
    last = paginate(session, stmt, PageParams(limit=2, offset=4))
    beyond = paginate(session, stmt, PageParams(limit=2, offset=50))

    assert (first["total"], len(first["items"]), first["has_more"]) == (5, 2, True)
    assert (last["total"], len(last["items"]), last["has_more"]) == (5, 1, False)
    assert (beyond["total"], beyond["items"], beyond["has_more"]) == (5, [], False)


def test_total_counts_filtered_rows_not_the_table(session):
    seed(session, 6)
    stmt = select(Project).where(Project.name.in_(["cat-01", "cat-02"]))
    result = paginate(session, stmt, PageParams(limit=1, offset=0))
    assert (result["total"], len(result["items"]), result["has_more"]) == (2, 1, True)


def test_sort_direction_and_whitelist(session):
    seed(session, 3)
    columns = {"name": Project.name}
    ascending = paginate(
        session,
        apply_sort(select(Project), "name", columns, Project.id),
        PageParams(limit=10, offset=0),
    )
    descending = paginate(
        session,
        apply_sort(select(Project), "-name", columns, Project.id),
        PageParams(limit=10, offset=0),
    )

    assert [c.name for c in ascending["items"]] == ["cat-00", "cat-01", "cat-02"]
    assert [c.name for c in descending["items"]] == ["cat-02", "cat-01", "cat-00"]
    with pytest.raises(HTTPException) as unknown:
        apply_sort(select(Project), "password_hash", columns, Project.id)
    assert unknown.value.status_code == 400


def test_ties_are_broken_by_id_so_pages_never_overlap(session):
    owner = _owner(session)
    for _ in range(9):
        make_project(session, owner, name="same-name")  # même valeur de tri partout
    stmt = apply_sort(select(Project), "name", {"name": Project.name}, Project.id)

    seen = []
    for offset in (0, 3, 6):
        seen += [c.id for c in paginate(session, stmt, PageParams(limit=3, offset=offset))["items"]]

    assert len(seen) == len(set(seen)) == 9


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("a%b", "%a\\%b%"), ("a_b", "%a\\_b%"), ("a\\b", "%a\\\\b%"), ("plain", "%plain%")],
)
def test_like_pattern_escapes_wildcards(raw, expected):
    assert like_pattern(raw) == expected


def test_date_range_bounds_and_inversion(session):
    stmt = select(Project)
    apply_date_range(
        stmt, Project.created_at, datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 2, 1, tzinfo=UTC)
    )
    with pytest.raises(HTTPException) as inverted:
        apply_date_range(
            stmt,
            Project.created_at,
            datetime(2021, 1, 1, tzinfo=UTC),
            datetime(2020, 1, 1, tzinfo=UTC),
        )
    assert inverted.value.status_code == 400
    assert apply_date_range(stmt, Project.created_at, None, None) is stmt


def test_limits_are_sane():
    assert 1 <= DEFAULT_LIMIT <= MAX_LIMIT <= 100
