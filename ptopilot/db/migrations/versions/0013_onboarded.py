"""users.onboarded_at and users.welcome_step: the guided /welcome flow's progress

Every user who exists when this runs is counted as onboarded (onboarded_at = now()), so no current user
is ever sent into the welcome steps; so is every user created later outside the welcome flow (the default).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The default covers users created by plain SQL, or by code deployed before this migration's code.
    op.add_column(
        "users",
        sa.Column("onboarded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    )
    op.execute("UPDATE users SET onboarded_at = now() WHERE onboarded_at IS NULL")
    op.add_column("users", sa.Column("welcome_step", sa.SmallInteger(), server_default="0", nullable=False))
    op.create_check_constraint("welcome_step", "users", "welcome_step BETWEEN 0 AND 4")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_welcome_step"), "users", type_="check")
    op.drop_column("users", "welcome_step")
    op.drop_column("users", "onboarded_at")
