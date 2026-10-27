"""002 partition check results table

Revision ID: 002_partition_check_results
Revises: 001_initial_schema
Create Date: 2026-10-27 15:30:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = "002_partition_check_results"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE check_results RENAME TO check_results_old;")

    op.execute(
        """
        CREATE TABLE check_results (
            id BIGSERIAL,
            monitor_id UUID NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            job_id UUID NOT NULL,
            status_code INTEGER,
            response_time_ms INTEGER,
            is_success BOOLEAN NOT NULL,
            error_message TEXT,
            ssl_days_remaining INTEGER,
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
        """
    )

    op.execute("CREATE TABLE check_results_default PARTITION OF check_results DEFAULT;")
    op.execute("CREATE INDEX idx_check_results_monitor_created ON check_results (monitor_id, created_at DESC);")

    op.execute(
        """
        INSERT INTO check_results (
            id, monitor_id, job_id, status_code, response_time_ms,
            is_success, error_message, ssl_days_remaining, created_at
        )
        SELECT id, monitor_id, job_id, status_code, response_time_ms,
               is_success, error_message, ssl_days_remaining, created_at
        FROM check_results_old;
        """
    )

    op.execute("DROP TABLE check_results_old;")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE check_results RENAME TO check_results_partitioned;")

    op.execute(
        """
        CREATE TABLE check_results (
            id BIGSERIAL PRIMARY KEY,
            monitor_id UUID NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
            job_id UUID NOT NULL,
            status_code INTEGER,
            response_time_ms INTEGER,
            is_success BOOLEAN NOT NULL,
            error_message TEXT,
            ssl_days_remaining INTEGER,
            created_at TIMESTAMPTZ NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX idx_check_results_monitor_created ON check_results (monitor_id, created_at DESC);")

    op.execute(
        """
        INSERT INTO check_results (
            id, monitor_id, job_id, status_code, response_time_ms,
            is_success, error_message, ssl_days_remaining, created_at
        )
        SELECT id, monitor_id, job_id, status_code, response_time_ms,
               is_success, error_message, ssl_days_remaining, created_at
        FROM check_results_partitioned;
        """
    )

    op.execute("DROP TABLE check_results_partitioned CASCADE;")
