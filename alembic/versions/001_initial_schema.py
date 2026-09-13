"""001 initial schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-13 13:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "monitors",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("method", sa.String(length=10), server_default="GET", nullable=False),
        sa.Column("interval_seconds", sa.Integer(), server_default="60", nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default="10", nullable=False),
        sa.Column("expected_status_code", sa.Integer(), server_default="200", nullable=False),
        sa.Column("consecutive_threshold", sa.Integer(), server_default="3", nullable=False),
        sa.Column("current_status", sa.String(length=20), server_default="UNKNOWN", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_monitors_user_id", "monitors", ["user_id"])

    op.create_table(
        "check_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("monitor_id", sa.Uuid(as_uuid=True), sa.ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("is_success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("ssl_days_remaining", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_check_results_monitor_created", "check_results", ["monitor_id", sa.text("created_at DESC")])

    op.create_table(
        "hourly_uptime_summary",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("monitor_id", sa.Uuid(as_uuid=True), sa.ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hour_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_checks", sa.Integer(), nullable=False),
        sa.Column("success_checks", sa.Integer(), nullable=False),
        sa.Column("avg_response_time_ms", sa.Integer(), nullable=False),
        sa.Column("uptime_percentage", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.UniqueConstraint("monitor_id", "hour_timestamp", name="uq_monitor_hour"),
    )
    op.create_index("idx_hourly_summary_monitor_time", "hourly_uptime_summary", ["monitor_id", sa.text("hour_timestamp DESC")])

    op.create_table(
        "alert_configs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("monitor_id", sa.Uuid(as_uuid=True), sa.ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("alert_configs")
    op.drop_index("idx_hourly_summary_monitor_time", table_name="hourly_uptime_summary")
    op.drop_table("hourly_uptime_summary")
    op.drop_index("idx_check_results_monitor_created", table_name="check_results")
    op.drop_table("check_results")
    op.drop_index("ix_monitors_user_id", table_name="monitors")
    op.drop_table("monitors")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
