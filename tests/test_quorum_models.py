import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.api_gateway.services.monitor_service import MonitorService
from services.common.models import CheckResult, HourlyUptimeSummary, Monitor, User
from services.common.rollup import aggregate_hourly_uptime
from services.common.schemas import MonitorCreate, MonitorUpdate


def test_monitor_create_schema_valid_quorum() -> None:
    schema = MonitorCreate(
        name="Test API",
        url="https://1.1.1.1/health",
        quorum_enabled=True,
        quorum_threshold=2,
        quorum_regions=["vn-han", "sg-sin", "us-iad"],
    )
    assert schema.quorum_enabled is True
    assert schema.quorum_threshold == 2
    assert len(schema.quorum_regions) == 3


def test_monitor_create_schema_rejects_threshold_greater_than_regions() -> None:
    with pytest.raises(ValidationError, match="quorum_threshold cannot exceed"):
        MonitorCreate(
            name="Invalid Threshold",
            url="https://1.1.1.1/health",
            quorum_enabled=True,
            quorum_threshold=4,
            quorum_regions=["vn-han", "sg-sin", "us-iad"],
        )


def test_monitor_create_schema_rejects_less_than_two_regions_when_enabled() -> None:
    with pytest.raises(ValidationError, match="at least 2 regions"):
        MonitorCreate(
            name="Single Region Quorum",
            url="https://1.1.1.1/health",
            quorum_enabled=True,
            quorum_threshold=1,
            quorum_regions=["vn-han"],
        )


def test_monitor_update_schema_validates_threshold_and_regions() -> None:
    with pytest.raises(ValidationError, match="quorum_threshold cannot exceed"):
        MonitorUpdate(
            quorum_enabled=True,
            quorum_threshold=3,
            quorum_regions=["vn-han", "sg-sin"],
        )


@pytest.mark.asyncio
async def test_monitor_model_default_values(db_session: AsyncSession) -> None:
    user = User(email="quorum_test@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="Default Quorum Monitor",
        url="https://1.1.1.1/health",
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    assert monitor.quorum_enabled is False
    assert monitor.quorum_threshold == 2
    assert monitor.quorum_regions == ["vn-han", "sg-sin", "us-iad"]


@pytest.mark.asyncio
async def test_check_result_model_defaults_and_fields(db_session: AsyncSession) -> None:
    user = User(email="cr_test@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="CR Monitor",
        url="https://1.1.1.1/health",
    )
    db_session.add(monitor)
    await db_session.flush()

    result_default = CheckResult(
        monitor_id=monitor.id,
        job_id=uuid.uuid4(),
        status_code=200,
        response_time_ms=45,
        is_success=True,
    )
    db_session.add(result_default)

    result_suppressed = CheckResult(
        monitor_id=monitor.id,
        job_id=uuid.uuid4(),
        status_code=504,
        response_time_ms=5000,
        is_success=False,
        region_id="vn-han",
        is_suppressed=True,
    )
    db_session.add(result_suppressed)

    await db_session.commit()
    await db_session.refresh(result_default)
    await db_session.refresh(result_suppressed)

    assert result_default.region_id == "vn-han"
    assert result_default.is_suppressed is False

    assert result_suppressed.region_id == "vn-han"
    assert result_suppressed.is_suppressed is True


@pytest.mark.asyncio
async def test_rollup_counts_suppressed_as_successful_uptime(db_session: AsyncSession) -> None:
    user = User(email="rollup_test@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="Rollup Quorum Monitor",
        url="https://1.1.1.1/health",
    )
    db_session.add(monitor)
    await db_session.flush()

    target_hour = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)

    r1 = CheckResult(
        monitor_id=monitor.id,
        job_id=uuid.uuid4(),
        status_code=200,
        response_time_ms=50,
        is_success=True,
        is_suppressed=False,
        region_id="sg-sin",
        created_at=target_hour.replace(minute=5),
    )
    r2 = CheckResult(
        monitor_id=monitor.id,
        job_id=uuid.uuid4(),
        status_code=500,
        response_time_ms=1000,
        is_success=False,
        is_suppressed=True,
        region_id="vn-han",
        created_at=target_hour.replace(minute=15),
    )
    r3 = CheckResult(
        monitor_id=monitor.id,
        job_id=uuid.uuid4(),
        status_code=503,
        response_time_ms=1500,
        is_success=False,
        is_suppressed=False,
        region_id="sg-sin",
        created_at=target_hour.replace(minute=25),
    )
    r4 = CheckResult(
        monitor_id=monitor.id,
        job_id=uuid.uuid4(),
        status_code=200,
        response_time_ms=60,
        is_success=True,
        is_suppressed=False,
        region_id="us-iad",
        created_at=target_hour.replace(minute=35),
    )

    db_session.add_all([r1, r2, r3, r4])
    await db_session.commit()

    processed = await aggregate_hourly_uptime(db_session, target_hour=target_hour)
    assert processed == 1

    stmt = select(HourlyUptimeSummary).where(
        HourlyUptimeSummary.monitor_id == monitor.id,
        HourlyUptimeSummary.hour_timestamp == target_hour,
    )
    summary_result = await db_session.execute(stmt)
    summary = summary_result.scalar_one()

    assert summary.total_checks == 4
    assert summary.success_checks == 3
    assert summary.uptime_percentage == Decimal("75.00")


@pytest.mark.asyncio
async def test_monitor_detail_fallback_counts_suppressed_as_success(db_session: AsyncSession) -> None:
    user = User(email="detail_suppressed@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="Detail Suppressed Monitor",
        url="https://1.1.1.1/health",
    )
    db_session.add(monitor)
    await db_session.flush()

    c1 = CheckResult(
        monitor_id=monitor.id,
        job_id=uuid.uuid4(),
        status_code=200,
        response_time_ms=50,
        is_success=True,
        is_suppressed=False,
    )
    c2 = CheckResult(
        monitor_id=monitor.id,
        job_id=uuid.uuid4(),
        status_code=500,
        response_time_ms=1200,
        is_success=False,
        is_suppressed=True,
    )
    db_session.add_all([c1, c2])
    await db_session.commit()

    service = MonitorService(db=db_session, redis_client=AsyncMock())
    detail = await service.get_monitor_detail(current_user=user, monitor_id=monitor.id)

    assert detail.uptime_percentage_24h == Decimal("100.00")


@pytest.mark.asyncio
async def test_update_monitor_partial_threshold_exceeds_existing_regions(db_session: AsyncSession) -> None:
    user = User(email="update_quorum@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="Update Threshold Monitor",
        url="https://1.1.1.1/health",
        quorum_enabled=True,
        quorum_threshold=2,
        quorum_regions=["vn-han", "sg-sin", "us-iad"],
    )
    db_session.add(monitor)
    await db_session.commit()

    service = MonitorService(db=db_session, redis_client=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await service.update_monitor(
            current_user=user,
            monitor_id=monitor.id,
            monitor_in=MonitorUpdate(quorum_threshold=4),
        )
    assert exc_info.value.status_code == 422
    assert "cannot exceed" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_monitor_partial_regions_less_than_two_when_enabled(db_session: AsyncSession) -> None:
    user = User(email="update_regions@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="Update Regions Monitor",
        url="https://1.1.1.1/health",
        quorum_enabled=True,
        quorum_threshold=1,
        quorum_regions=["vn-han", "sg-sin"],
    )
    db_session.add(monitor)
    await db_session.commit()

    service = MonitorService(db=db_session, redis_client=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await service.update_monitor(
            current_user=user,
            monitor_id=monitor.id,
            monitor_in=MonitorUpdate(quorum_regions=["vn-han"]),
        )
    assert exc_info.value.status_code == 422
    assert "at least 2 regions" in exc_info.value.detail
