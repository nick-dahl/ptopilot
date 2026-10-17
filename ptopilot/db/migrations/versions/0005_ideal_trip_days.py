"""preferred trip length

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17

Adds the optional users.ideal_trip_days (days away from home). NULL means no preference. When set, it must
lie within the user's min..max trip length.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("ideal_trip_days", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "ideal_trip_days",
        "users",
        "ideal_trip_days IS NULL OR (min_trip_days <= ideal_trip_days AND ideal_trip_days <= max_trip_days)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_ideal_trip_days"), "users", type_="check")
    op.drop_column("users", "ideal_trip_days")
