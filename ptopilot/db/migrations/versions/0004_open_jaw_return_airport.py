"""open-jaw return airport

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16

Adds `return_airport` (fly home from) to route_queries, price_observations and route_baselines, and widens
trackers.destination_code from 8 to 32 characters (e.g. CAMINO_PORTUGUES).
Existing rows are all round trips, so they are backfilled with their dest_airport before the column
becomes NOT NULL. Alembic doesn't detect primary-key changes, so route_baselines' key is rebuilt by hand.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("route_queries", "price_observations", "route_baselines")


def upgrade() -> None:
    op.alter_column("trackers", "destination_code", type_=sa.String(length=32), existing_nullable=False)
    for table in TABLES:
        op.add_column(table, sa.Column("return_airport", sa.String(length=3), nullable=True))
        op.execute(f"UPDATE {table} SET return_airport = dest_airport")
        op.alter_column(table, "return_airport", nullable=False)

    op.drop_constraint("uq_route_queries_origin", "route_queries", type_="unique")
    op.create_unique_constraint(
        "uq_route_queries_trip",
        "route_queries",
        ["origin", "dest_airport", "return_airport", "depart_date", "return_date"],
    )

    op.drop_constraint("pk_route_baselines", "route_baselines", type_="primary")
    op.create_primary_key(
        "pk_route_baselines",
        "route_baselines",
        ["origin", "dest_airport", "return_airport", "month", "length_bucket"],
    )


def downgrade() -> None:
    # Open-jaw rows can't be represented without return_airport; drop them first.
    op.execute("DELETE FROM route_queries WHERE return_airport <> dest_airport")
    op.execute("DELETE FROM price_observations WHERE return_airport <> dest_airport")
    op.execute("DELETE FROM route_baselines WHERE return_airport <> dest_airport")

    op.drop_constraint("pk_route_baselines", "route_baselines", type_="primary")
    op.create_primary_key(
        "pk_route_baselines", "route_baselines", ["origin", "dest_airport", "month", "length_bucket"]
    )
    op.drop_constraint("uq_route_queries_trip", "route_queries", type_="unique")
    op.create_unique_constraint(
        "uq_route_queries_origin", "route_queries", ["origin", "dest_airport", "depart_date", "return_date"]
    )
    for table in TABLES:
        op.drop_column(table, "return_airport")
    # Codes longer than 8 characters (e.g. CAMINO_PORTUGUES) can't survive the narrower column.
    op.execute("DELETE FROM trackers WHERE length(destination_code) > 8")
    op.alter_column("trackers", "destination_code", type_=sa.String(length=8), existing_nullable=False)
