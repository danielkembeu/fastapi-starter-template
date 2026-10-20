"""Les migrations sont la SEULE source du schéma : elles doivent être cohérentes avec les modèles.

Ces tests tournent sur une base SQLite jetable. La CI refait la même chose sur PostgreSQL
(types enum, déclencheur d'audit) : voir `.github/workflows/ci.yaml`.
"""

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

import app.modules
from alembic import command

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(name="alembic_config")
def alembic_config_fixture(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.attributes["url"] = url
    return config, url


def test_there_is_exactly_one_migration_head(alembic_config):
    config, _ = alembic_config
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"plusieurs têtes Alembic (branches à fusionner) : {heads}"


def test_migrations_build_the_schema_declared_by_the_models(alembic_config):
    config, url = alembic_config
    command.upgrade(config, "head")

    tables = set(inspect(create_engine(url)).get_table_names())
    assert set(SQLModel.metadata.tables) <= tables


def test_models_and_migrations_have_not_drifted(alembic_config):
    """Un modèle modifié sans migration fait échouer ce test (`make rev m="…"` pour la créer)."""
    config, url = alembic_config
    command.upgrade(config, "head")

    with create_engine(url).connect() as connection:
        context = MigrationContext.configure(connection)
        diff = compare_metadata(context, SQLModel.metadata)
    assert diff == [], f"modèles et migrations divergent : {diff}"


def test_migrations_can_be_rolled_back_and_replayed(alembic_config):
    config, url = alembic_config
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}

    command.upgrade(config, "head")  # le rejeu prouve que le retour arrière ne laisse rien derrière
    assert set(SQLModel.metadata.tables) <= set(inspect(create_engine(url)).get_table_names())


def test_every_migration_has_a_downgrade():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    for revision in ScriptDirectory.from_config(config).walk_revisions():
        source = Path(revision.path).read_text(encoding="utf-8")
        assert "def downgrade" in source
        assert "pass\n" not in source.split("def downgrade", 1)[1].split("def ", 1)[0], (
            f"{revision.revision} : downgrade vide"
        )
