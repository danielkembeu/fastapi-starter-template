"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401 — requis par les types `sqlmodel.sql.sqltypes.AutoString` générés
from alembic import op
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema.

    Une migration doit se pouvoir défaire ET rejouer : supprimer aussi les types enum PostgreSQL
    (`sa.Enum(name="...").drop(op.get_bind(), checkfirst=True)`), que `drop_table` laisse en base.
    """
    ${downgrades if downgrades else "pass"}
