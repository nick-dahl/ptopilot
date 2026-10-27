"""longest layover on observations, misery verdict on candidates

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26

Price observations record each option's longest layover; candidates get a verdict and a note.
Nullable columns and a defaulted verdict only; existing rows are unchanged ('ok').
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("price_observations", sa.Column("longest_layover_min", sa.SmallInteger(), nullable=True))
    op.add_column(
        "price_observations", sa.Column("longest_layover_airport", sa.String(length=3), nullable=True)
    )
    op.add_column(
        "candidates",
        sa.Column("verdict", sa.String(length=9), server_default="ok", nullable=False),
    )
    op.add_column("candidates", sa.Column("misery_note", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_candidates_verdict"), "candidates", "verdict IN ('ok', 'forgiven', 'ruled_out')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_candidates_verdict"), "candidates", type_="check")
    op.drop_column("candidates", "misery_note")
    op.drop_column("candidates", "verdict")
    op.drop_column("price_observations", "longest_layover_airport")
    op.drop_column("price_observations", "longest_layover_min")
