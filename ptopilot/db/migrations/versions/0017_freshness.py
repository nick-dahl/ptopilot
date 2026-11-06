"""freshness: 'audit' and 'second' shortlist reasons; live_checks.route_specific

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_shortlist_entries_reason"), "shortlist_entries", type_="check")
    op.create_check_constraint(
        op.f("ck_shortlist_entries_reason"),
        "shortlist_entries",
        "reason IN ('deal', 'explore', 'audit', 'second')",
    )
    op.add_column(
        "live_checks",
        sa.Column("route_specific", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("live_checks", "route_specific")
    op.execute("DELETE FROM shortlist_entries WHERE reason IN ('audit', 'second')")
    op.drop_constraint(op.f("ck_shortlist_entries_reason"), "shortlist_entries", type_="check")
    op.create_check_constraint(
        op.f("ck_shortlist_entries_reason"), "shortlist_entries", "reason IN ('deal', 'explore')"
    )
