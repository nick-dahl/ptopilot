"""place_photos: each place's cover photo from Wikimedia Commons, with its attribution

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "place_photos",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("licence", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=4), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('ok','none')", name=op.f("ck_place_photos_status")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_place_photos")),
    )


def downgrade() -> None:
    op.drop_table("place_photos")
