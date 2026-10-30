"""related_links and related_checks: related places a user accepted, and their cheap-fare checks

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "related_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("airport", sa.String(length=3), nullable=False),
        sa.Column("place_code", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('accepted','dismissed')", name=op.f("ck_related_links_status")),
        sa.ForeignKeyConstraint(
            ["tracker_id"],
            ["trackers.id"],
            name=op.f("fk_related_links_tracker_id_trackers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_related_links_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_related_links")),
        sa.UniqueConstraint("tracker_id", "airport", name=op.f("uq_related_links_tracker_id")),
    )
    op.create_index(op.f("ix_related_links_user_id"), "related_links", ["user_id"])
    op.create_table(
        "related_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("link_id", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("airport", sa.String(length=3), nullable=False),
        sa.Column("depart_date", sa.Date(), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=False),
        sa.Column("cached_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("typical_median", sa.Numeric(10, 2), nullable=False),
        sa.Column("live_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("pto_cost", sa.SmallInteger(), nullable=False),
        sa.Column("deep_link", sa.Text(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["link_id"],
            ["related_links.id"],
            name=op.f("fk_related_checks_link_id_related_links"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tracker_id"],
            ["trackers.id"],
            name=op.f("fk_related_checks_tracker_id_trackers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_related_checks_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_related_checks")),
    )
    op.create_index(op.f("ix_related_checks_run_date"), "related_checks", ["run_date"])


def downgrade() -> None:
    op.drop_index(op.f("ix_related_checks_run_date"), table_name="related_checks")
    op.drop_table("related_checks")
    op.drop_index(op.f("ix_related_links_user_id"), table_name="related_links")
    op.drop_table("related_links")
