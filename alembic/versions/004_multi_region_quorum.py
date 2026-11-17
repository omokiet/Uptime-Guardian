"""004 multi region quorum

Revision ID: 004_multi_region_quorum
Revises: 003_add_monitor_deleted_at
Create Date: 2026-11-17 12:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004_multi_region_quorum"
down_revision: Union[str, None] = "003_add_monitor_deleted_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            ALTER TABLE monitors
                ADD COLUMN IF NOT EXISTS quorum_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS quorum_threshold INTEGER NOT NULL DEFAULT 2,
                ADD COLUMN IF NOT EXISTS quorum_regions VARCHAR(32)[] NOT NULL DEFAULT '{"vn-han", "sg-sin", "us-iad"}';
            """
        )
        op.execute(
            """
            ALTER TABLE check_results
                ADD COLUMN IF NOT EXISTS region_id VARCHAR(32) NOT NULL DEFAULT 'vn-han',
                ADD COLUMN IF NOT EXISTS is_suppressed BOOLEAN NOT NULL DEFAULT FALSE;
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_check_results_region_created
                ON check_results (region_id, created_at DESC);
            """
        )
    else:
        with op.batch_alter_table("monitors") as batch_op:
            batch_op.add_column(
                sa.Column("quorum_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )
            batch_op.add_column(
                sa.Column("quorum_threshold", sa.Integer(), nullable=False, server_default=sa.text("2"))
            )
            batch_op.add_column(
                sa.Column(
                    "quorum_regions",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text('\'["vn-han", "sg-sin", "us-iad"]\''),
                )
            )
        with op.batch_alter_table("check_results") as batch_op:
            batch_op.add_column(
                sa.Column("region_id", sa.String(32), nullable=False, server_default=sa.text("'vn-han'"))
            )
            batch_op.add_column(
                sa.Column("is_suppressed", sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )
            batch_op.create_index("ix_check_results_region_created", ["region_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_check_results_region_created;")
        op.execute(
            """
            ALTER TABLE check_results
                DROP COLUMN IF EXISTS is_suppressed,
                DROP COLUMN IF EXISTS region_id;
            """
        )
        op.execute(
            """
            ALTER TABLE monitors
                DROP COLUMN IF EXISTS quorum_regions,
                DROP COLUMN IF EXISTS quorum_threshold,
                DROP COLUMN IF EXISTS quorum_enabled;
            """
        )
    else:
        with op.batch_alter_table("check_results") as batch_op:
            batch_op.drop_index("ix_check_results_region_created")
            batch_op.drop_column("is_suppressed")
            batch_op.drop_column("region_id")
        with op.batch_alter_table("monitors") as batch_op:
            batch_op.drop_column("quorum_regions")
            batch_op.drop_column("quorum_threshold")
            batch_op.drop_column("quorum_enabled")
