"""003 add monitor deleted_at

Revision ID: 003_add_monitor_deleted_at
Revises: 002_partition_check_results
Create Date: 2026-11-15 20:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003_add_monitor_deleted_at"
down_revision: Union[str, None] = "002_partition_check_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("monitors", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_monitors_user_deleted", "monitors", ["user_id", "deleted_at"])


def downgrade() -> None:
    op.drop_index("idx_monitors_user_deleted", table_name="monitors")
    op.drop_column("monitors", "deleted_at")
