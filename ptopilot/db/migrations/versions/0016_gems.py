"""gems: weekly hidden-gem issues per person and their fare checks

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gem_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("gem_slug", sa.String(length=64), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_gem_issues_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gem_issues")),
        sa.UniqueConstraint("user_id", "gem_slug", name=op.f("uq_gem_issues_user_id")),
    )
    op.create_table(
        "gem_fares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("gem_slug", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("airport", sa.String(length=3), nullable=False),
        sa.Column("return_airport", sa.String(length=3), nullable=False),
        sa.Column("depart_date", sa.Date(), nullable=True),
        sa.Column("return_date", sa.Date(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=6), nullable=False),
        sa.Column("fits", sa.Boolean(), nullable=True),
        sa.Column("fit_month", sa.SmallInteger(), nullable=True),
        sa.Column("pto_cost", sa.SmallInteger(), nullable=True),
        sa.Column("deep_link", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.CheckConstraint("status IN ('found','none','failed')", name=op.f("ck_gem_fares_status")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_gem_fares_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gem_fares")),
    )
    op.create_index(op.f("ix_gem_fares_run_date"), "gem_fares", ["run_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_gem_fares_run_date"), table_name="gem_fares")
    op.drop_table("gem_fares")
    op.drop_table("gem_issues")
