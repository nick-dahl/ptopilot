"""candidates.duration_thin: a dip today but too little history to estimate its length

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-30

Lets the display say "not enough history yet" instead of showing nothing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidates", sa.Column("duration_thin", sa.Boolean(), server_default="false", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("candidates", "duration_thin")
