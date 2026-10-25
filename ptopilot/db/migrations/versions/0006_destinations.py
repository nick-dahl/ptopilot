"""destinations in the database

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25

User-added places (destinations) with climate-generated seasons, and the optional trackers.target_days
(days away the user wants for this place).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "destinations",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("airports", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("return_airports", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("added_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('city', 'region', 'route')", name=op.f("ck_destinations_kind")),
        sa.ForeignKeyConstraint(
            ["added_by"], ["users.id"], name=op.f("fk_destinations_added_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_destinations")),
    )
    op.create_table(
        "destination_seasons",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("months", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("notes", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["code"],
            ["destinations.code"],
            name=op.f("fk_destination_seasons_code_destinations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_destination_seasons")),
    )
    op.add_column("trackers", sa.Column("target_days", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "target_days", "trackers", "target_days IS NULL OR target_days BETWEEN 2 AND 60"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_trackers_target_days"), "trackers", type_="check")
    op.drop_column("trackers", "target_days")
    op.drop_table("destination_seasons")
    op.drop_table("destinations")
