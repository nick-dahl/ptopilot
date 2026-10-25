"""planning years, planned trips, one tracker per destination

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25

Each user plans one year at a time: a PTO budget per year and the trackers (destinations) picked for it.
Existing users are seeded from their travel windows: one planning year per distinct window start year,
with every active tracker planned in each of those years. A user can track a destination only once.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    duplicates = conn.execute(
        sa.text(
            "SELECT count(*) FROM (SELECT 1 FROM trackers GROUP BY user_id, destination_code"
            " HAVING count(*) > 1) d"
        )
    ).scalar_one()
    if duplicates:
        raise RuntimeError(
            f"{duplicates} duplicate (user_id, destination_code) tracker pairs; resolve them before migrating"
        )

    op.create_unique_constraint(op.f("uq_trackers_user_id"), "trackers", ["user_id", "destination_code"])
    op.create_table(
        "planning_years",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("pto_days", sa.SmallInteger(), nullable=False),
        sa.Column("other_time_off", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "pto_days >= 0 AND other_time_off >= 0 AND other_time_off <= pto_days",
            name=op.f("ck_planning_years_pto_days"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_planning_years_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "year", name=op.f("pk_planning_years")),
    )
    op.create_table(
        "planned_trips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("tracker_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tracker_id"],
            ["trackers.id"],
            name=op.f("fk_planned_trips_tracker_id_trackers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_planned_trips_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_planned_trips")),
        sa.UniqueConstraint("tracker_id", "year", name=op.f("uq_planned_trips_tracker_id")),
    )
    op.create_index(op.f("ix_planned_trips_user_id"), "planned_trips", ["user_id"], unique=False)

    conn.execute(
        sa.text(
            "INSERT INTO planning_years (user_id, year, pto_days, other_time_off)"
            " SELECT u.id, y.year, u.pto_days_total, u.pto_committed FROM users u"
            " JOIN (SELECT DISTINCT user_id, extract(year FROM start_date)::int AS year"
            " FROM travel_windows) y ON y.user_id = u.id"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO planned_trips (user_id, year, tracker_id)"
            " SELECT t.user_id, p.year, t.id FROM trackers t"
            " JOIN planning_years p ON p.user_id = t.user_id WHERE t.active"
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_planned_trips_user_id"), table_name="planned_trips")
    op.drop_table("planned_trips")
    op.drop_table("planning_years")
    op.drop_constraint(op.f("uq_trackers_user_id"), "trackers", type_="unique")
