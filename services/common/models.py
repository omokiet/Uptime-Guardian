import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from services.common.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    monitors: Mapped[List["Monitor"]] = relationship(
        "Monitor",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(String(10), default="GET", nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    expected_status_code: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    consecutive_threshold: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    current_status: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="monitors")
    check_results: Mapped[List["CheckResult"]] = relationship(
        "CheckResult",
        back_populates="monitor",
        cascade="all, delete-orphan",
    )
    alert_configs: Mapped[List["AlertConfig"]] = relationship(
        "AlertConfig",
        back_populates="monitor",
        cascade="all, delete-orphan",
    )
    hourly_summaries: Mapped[List["HourlyUptimeSummary"]] = relationship(
        "HourlyUptimeSummary",
        back_populates="monitor",
        cascade="all, delete-orphan",
    )


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ssl_days_remaining: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    monitor: Mapped["Monitor"] = relationship("Monitor", back_populates="check_results")

    __table_args__ = (
        Index("idx_check_results_monitor_created", "monitor_id", created_at.desc()),
    )


class HourlyUptimeSummary(Base):
    __tablename__ = "hourly_uptime_summary"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    hour_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    total_checks: Mapped[int] = mapped_column(Integer, nullable=False)
    success_checks: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    uptime_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    monitor: Mapped["Monitor"] = relationship("Monitor", back_populates="hourly_summaries")

    __table_args__ = (
        UniqueConstraint("monitor_id", "hour_timestamp", name="uq_monitor_hour"),
        Index("idx_hourly_summary_monitor_time", "monitor_id", hour_timestamp.desc()),
    )


class AlertConfig(Base):
    __tablename__ = "alert_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    monitor: Mapped["Monitor"] = relationship("Monitor", back_populates="alert_configs")
