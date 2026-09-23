import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import CheckResult, HourlyUptimeSummary, Monitor, User
from services.common.rollup import aggregate_hourly_uptime, purge_old_check_results


@pytest.mark.asyncio
async def test_rollup_calculates_correct_stats(db_session: AsyncSession, test_user: User) -> None:
    monitor = Monitor(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="Test API Monitor",
        url="https://api.example.com/health",
        interval_seconds=60,
    )
    db_session.add(monitor)
    await db_session.commit()

    target_hour = datetime(2026, 9, 23, 10, 0, 0, tzinfo=timezone.utc)

    checks = [
        CheckResult(
            monitor_id=monitor.id,
            job_id=uuid.uuid4(),
            status_code=200,
            response_time_ms=100,
            is_success=True,
            created_at=target_hour + timedelta(minutes=5),
        ),
        CheckResult(
            monitor_id=monitor.id,
            job_id=uuid.uuid4(),
            status_code=200,
            response_time_ms=200,
            is_success=True,
            created_at=target_hour + timedelta(minutes=15),
        ),
        CheckResult(
            monitor_id=monitor.id,
            job_id=uuid.uuid4(),
            status_code=200,
            response_time_ms=300,
            is_success=True,
            created_at=target_hour + timedelta(minutes=30),
        ),
        CheckResult(
            monitor_id=monitor.id,
            job_id=uuid.uuid4(),
            status_code=500,
            response_time_ms=400,
            is_success=False,
            created_at=target_hour + timedelta(minutes=45),
        ),
    ]
    db_session.add_all(checks)
    await db_session.commit()

    processed_count = await aggregate_hourly_uptime(db_session, target_hour=target_hour)
    assert processed_count == 1

    stmt = select(HourlyUptimeSummary).where(
        HourlyUptimeSummary.monitor_id == monitor.id,
        HourlyUptimeSummary.hour_timestamp == target_hour,
    )
    result = await db_session.execute(stmt)
    summary = result.scalar_one_or_none()

    assert summary is not None
    assert summary.total_checks == 4
    assert summary.success_checks == 3
    assert summary.avg_response_time_ms == 250
    assert summary.uptime_percentage == Decimal("75.00")


@pytest.mark.asyncio
async def test_rollup_idempotency_upsert(db_session: AsyncSession, test_user: User) -> None:
    monitor = Monitor(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="Idempotent Test",
        url="https://api.example.com/idempotent",
    )
    db_session.add(monitor)
    await db_session.commit()

    target_hour = datetime(2026, 9, 23, 11, 0, 0, tzinfo=timezone.utc)

    db_session.add(
        CheckResult(
            monitor_id=monitor.id,
            job_id=uuid.uuid4(),
            status_code=200,
            response_time_ms=100,
            is_success=True,
            created_at=target_hour + timedelta(minutes=10),
        )
    )
    await db_session.commit()

    await aggregate_hourly_uptime(db_session, target_hour=target_hour)

    db_session.add(
        CheckResult(
            monitor_id=monitor.id,
            job_id=uuid.uuid4(),
            status_code=500,
            response_time_ms=200,
            is_success=False,
            created_at=target_hour + timedelta(minutes=20),
        )
    )
    await db_session.commit()

    await aggregate_hourly_uptime(db_session, target_hour=target_hour)

    stmt = select(HourlyUptimeSummary).where(
        HourlyUptimeSummary.monitor_id == monitor.id,
        HourlyUptimeSummary.hour_timestamp == target_hour,
    )
    results = (await db_session.execute(stmt)).scalars().all()
    assert len(results) == 1

    summary = results[0]
    assert summary.total_checks == 2
    assert summary.success_checks == 1
    assert summary.avg_response_time_ms == 150
    assert summary.uptime_percentage == Decimal("50.00")


@pytest.mark.asyncio
async def test_rollup_skips_when_no_checks(db_session: AsyncSession, test_user: User) -> None:
    monitor = Monitor(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="Empty Monitor",
        url="https://api.example.com/empty",
    )
    db_session.add(monitor)
    await db_session.commit()

    target_hour = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    processed_count = await aggregate_hourly_uptime(db_session, target_hour=target_hour)
    assert processed_count == 0

    count = await db_session.scalar(select(func.count(HourlyUptimeSummary.id)))
    assert count == 0


@pytest.mark.asyncio
async def test_retention_purges_old_raw_logs(db_session: AsyncSession, test_user: User) -> None:
    monitor = Monitor(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="Retention Monitor",
        url="https://api.example.com/retention",
    )
    db_session.add(monitor)
    await db_session.commit()

    now = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    old_date = now - timedelta(days=8)
    recent_date = now - timedelta(days=2)

    old_checks = [
        CheckResult(
            monitor_id=monitor.id,
            job_id=uuid.uuid4(),
            status_code=200,
            response_time_ms=100,
            is_success=True,
            created_at=old_date,
        ),
        CheckResult(
            monitor_id=monitor.id,
            job_id=uuid.uuid4(),
            status_code=200,
            response_time_ms=120,
            is_success=True,
            created_at=old_date + timedelta(minutes=10),
        ),
    ]
    recent_checks = [
        CheckResult(
            monitor_id=monitor.id,
            job_id=uuid.uuid4(),
            status_code=200,
            response_time_ms=110,
            is_success=True,
            created_at=recent_date,
        ),
        CheckResult(
            monitor_id=monitor.id,
            job_id=uuid.uuid4(),
            status_code=200,
            response_time_ms=115,
            is_success=True,
            created_at=recent_date + timedelta(minutes=15),
        ),
    ]

    db_session.add_all(old_checks + recent_checks)
    await db_session.commit()

    deleted = await purge_old_check_results(
        db_session,
        retention_days=7,
        current_time=now,
        batch_size=10,
    )
    assert deleted == 2

    remaining = (await db_session.execute(select(CheckResult))).scalars().all()
    assert len(remaining) == 2
    assert all(c.created_at >= now - timedelta(days=7) for c in remaining)


@pytest.mark.asyncio
async def test_rollup_target_hour_none(db_session: AsyncSession) -> None:
    count = await aggregate_hourly_uptime(db_session, target_hour=None)
    assert count == 0
