import datetime
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import CheckResult, HourlyUptimeSummary, Monitor, User
from services.common.partitions import (
    drop_expired_partitions,
    ensure_future_partitions,
    get_iso_week_bounds,
)
from services.common.rollup import backfill_missing_hourly_summaries, purge_old_check_results


def test_iso_week_bounds():
    # Wednesday 2026-10-21
    dt_wed = datetime.datetime(2026, 10, 21, 14, 30, tzinfo=datetime.timezone.utc)
    start_dt, end_dt, name = get_iso_week_bounds(dt_wed)
    assert start_dt == datetime.datetime(2026, 10, 19, 0, 0, tzinfo=datetime.timezone.utc)
    assert end_dt == datetime.datetime(2026, 10, 26, 0, 0, tzinfo=datetime.timezone.utc)
    assert name == "check_results_y2026_w43"

    # Sunday 2026-10-25 23:59:59
    dt_sun = datetime.datetime(2026, 10, 25, 23, 59, 59, tzinfo=datetime.timezone.utc)
    s2, e2, name2 = get_iso_week_bounds(dt_sun)
    assert s2 == start_dt
    assert e2 == end_dt
    assert name2 == name

    # Monday 2026-10-26 00:00:00 -> Week 44
    dt_mon_next = datetime.datetime(2026, 10, 26, 0, 0, tzinfo=datetime.timezone.utc)
    s3, e3, name3 = get_iso_week_bounds(dt_mon_next)
    assert s3 == datetime.datetime(2026, 10, 26, 0, 0, tzinfo=datetime.timezone.utc)
    assert e3 == datetime.datetime(2026, 11, 2, 0, 0, tzinfo=datetime.timezone.utc)
    assert name3 == "check_results_y2026_w44"


@pytest.mark.asyncio
async def test_ensure_future_partitions_sqlite_noop(db_session: AsyncSession):
    # db_session is SQLite in tests
    created = await ensure_future_partitions(db_session, weeks_ahead=2)
    assert created == []


@pytest.mark.asyncio
async def test_ensure_future_partitions_postgresql_mock():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    mock_session.bind = mock_bind
    mock_session.get_bind.return_value = mock_bind
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    now_utc = datetime.datetime(2026, 10, 27, 12, 0, tzinfo=datetime.timezone.utc)
    created = await ensure_future_partitions(mock_session, weeks_ahead=2, current_time=now_utc)
    assert len(created) >= 2
    assert "check_results_default" in created
    assert "check_results_y2026_w44" in created
    assert mock_session.execute.called


@pytest.mark.asyncio
async def test_drop_expired_partitions_sqlite_noop(db_session: AsyncSession):
    dropped = await drop_expired_partitions(db_session, retention_days=7)
    assert dropped == []


@pytest.mark.asyncio
async def test_drop_expired_partitions_postgresql_mock():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_bind = MagicMock()
    mock_bind.dialect.name = "postgresql"
    mock_session.bind = mock_bind
    mock_session.get_bind.return_value = mock_bind

    # Mock partition query returning 3 partitions:
    # w40 (expired), w44 (current), default
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        "check_results_y2026_w40",
        "check_results_y2026_w44",
        "check_results_default",
    ]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    now_utc = datetime.datetime(2026, 10, 27, 12, 0, tzinfo=datetime.timezone.utc)
    dropped = await drop_expired_partitions(mock_session, retention_days=7, current_time=now_utc)
    assert "check_results_y2026_w40" in dropped
    assert "check_results_y2026_w44" not in dropped
    assert "check_results_default" not in dropped


@pytest.mark.asyncio
async def test_backfill_missing_hourly_summaries(db_session: AsyncSession, test_user: User):
    monitor = Monitor(
        user_id=test_user.id,
        name="Backfill Test",
        url="https://backfill.example.com",
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
    past_hour_1 = now_utc - datetime.timedelta(hours=2)
    past_hour_2 = now_utc - datetime.timedelta(hours=1)

    # Insert check results for past_hour_1 and past_hour_2
    res1 = CheckResult(
        monitor_id=monitor.id,
        job_id=monitor.id,
        status_code=200,
        response_time_ms=100,
        is_success=True,
        created_at=past_hour_1 + datetime.timedelta(minutes=15),
    )
    res2 = CheckResult(
        monitor_id=monitor.id,
        job_id=monitor.id,
        status_code=200,
        response_time_ms=120,
        is_success=True,
        created_at=past_hour_2 + datetime.timedelta(minutes=20),
    )
    db_session.add_all([res1, res2])
    await db_session.commit()

    # Backfill missing summaries for past 4 hours
    backfilled_count = await backfill_missing_hourly_summaries(db_session, hours=4, current_time=now_utc)
    assert backfilled_count >= 2

    # Verify rows in hourly_uptime_summary
    stmt = select(HourlyUptimeSummary).where(HourlyUptimeSummary.monitor_id == monitor.id)
    summaries = (await db_session.execute(stmt)).scalars().all()
    assert len(summaries) == 2

    # Running backfill again should find nothing missing
    again_count = await backfill_missing_hourly_summaries(db_session, hours=4, current_time=now_utc)
    assert again_count == 0


@pytest.mark.asyncio
async def test_purge_old_check_results_integration(db_session: AsyncSession):
    deleted = await purge_old_check_results(db_session, retention_days=7)
    assert deleted >= 0
