"""Le journal est en ajout seul AU NIVEAU DE LA BASE (déclencheur PostgreSQL) — pas seulement dans l'API."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.modules.audit.enums import AuditAction
from app.modules.audit.service import AuditService
from app.modules.audit.sql import APPEND_ONLY_DOWN, APPEND_ONLY_UP

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="nécessite PostgreSQL (make up && make test-pg)",
)


def _run_raw(engine, sql: str) -> None:
    """Exécute du SQL brut (le « % » du message d'erreur ne doit pas être lu comme un paramètre)."""
    raw = engine.raw_connection()
    try:
        raw.cursor().execute(sql)
        raw.commit()
    finally:
        raw.close()


@pytest.fixture(name="protected")
def protected_fixture(engine):
    """Pose le déclencheur de la migration sur la table de test (create_all ne le crée pas)."""
    _run_raw(engine, APPEND_ONLY_UP)
    yield
    _run_raw(engine, APPEND_ONLY_DOWN)


def test_the_database_itself_refuses_to_alter_or_erase_an_entry(engine, protected):
    with Session(engine) as session:
        AuditService.log(session, AuditAction.PROJECT_CREATED, details={"n": 1})
        session.commit()

    for statement in (
        "UPDATE audit_logs SET outcome = 'tampered'",
        "DELETE FROM audit_logs",
        "TRUNCATE audit_logs",
    ):
        with pytest.raises(DBAPIError, match="ajout seul"), engine.begin() as connection:
            connection.execute(text(statement))

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT outcome FROM audit_logs")).all()
    assert [r[0] for r in rows] == ["success"]  # intacte


def test_appending_still_works_under_the_trigger(engine, protected):
    with Session(engine) as session:
        for _ in range(3):
            AuditService.log(session, AuditAction.PROJECT_CREATED)
        session.commit()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM audit_logs")).scalar() == 3
