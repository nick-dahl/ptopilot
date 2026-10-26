"""booked trips on planned trips

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-25

A planned trip can carry the flight the user booked: its dates, price and the PTO it uses.
Nullable columns only; existing rows are unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("planned_trips", sa.Column("booked_depart", sa.Date(), nullable=True))
    op.add_column("planned_trips", sa.Column("booked_return", sa.Date(), nullable=True))
    op.add_column("planned_trips", sa.Column("booked_price", sa.Numeric(10, 2), nullable=True))
    op.add_column("planned_trips", sa.Column("booked_currency", sa.String(length=3), nullable=True))
    op.add_column("planned_trips", sa.Column("booked_pto", sa.SmallInteger(), nullable=True))
    op.add_column("planned_trips", sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_planned_trips_booked_dates"),
        "planned_trips",
        "(booked_depart IS NULL) = (booked_return IS NULL)"
        " AND (booked_depart IS NULL) = (booked_pto IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_planned_trips_booked_order"), "planned_trips", "booked_return >= booked_depart"
    )
    op.create_check_constraint(
        op.f("ck_planned_trips_booked_year"),
        "planned_trips",
        "booked_depart IS NULL OR extract(year from booked_depart) = year",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_planned_trips_booked_year"), "planned_trips", type_="check")
    op.drop_constraint(op.f("ck_planned_trips_booked_order"), "planned_trips", type_="check")
    op.drop_constraint(op.f("ck_planned_trips_booked_dates"), "planned_trips", type_="check")
    for column in (
        "booked_at",
        "booked_pto",
        "booked_currency",
        "booked_price",
        "booked_return",
        "booked_depart",
    ):
        op.drop_column("planned_trips", column)
