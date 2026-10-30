"""expected duration on candidates, instant-alert log, live-check purpose

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-30

Candidates get a nullable expected_days; alert_sends records instant alerts (one per user per day);
live_checks gets a purpose ('trip' for existing rows, 'return' for return-leg checks).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("candidates", sa.Column("expected_days", sa.SmallInteger(), nullable=True))
    op.add_column(
        "live_checks", sa.Column("purpose", sa.String(length=8), server_default="trip", nullable=False)
    )
    op.create_table(
        "alert_sends",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            name=op.f("fk_alert_sends_candidate_id_candidates"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tracker_id"],
            ["trackers.id"],
            name=op.f("fk_alert_sends_tracker_id_trackers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_alert_sends_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_sends")),
        sa.UniqueConstraint("user_id", "run_date", name=op.f("uq_alert_sends_user_id")),
    )
    op.create_index(op.f("ix_alert_sends_user_id"), "alert_sends", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_alert_sends_user_id"), table_name="alert_sends")
    op.drop_table("alert_sends")
    op.drop_column("live_checks", "purpose")
    op.drop_column("candidates", "expected_days")
