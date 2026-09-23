import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import Monitor, User
from services.scheduler.scheduler import (
    process_due_monitors,
    run_scheduler_loop,
    run_telemetry_maintenance_loop,
    sync_active_monitors_to_redis,
)


@pytest.mark.asyncio
async def test_scheduler_process_due_monitors(db_session: AsyncSession, test_user: User):
    monitor = Monitor(
        user_id=test_user.id,
        name="Scheduled Target",
        url="https://example.org",
        interval_seconds=60,
        timeout_seconds=5,
        expected_status_code=200,
        is_active=True,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    mock_redis = AsyncMock()
    mock_redis.eval = AsyncMock(return_value=[str(monitor.id)])
    mock_pipeline = AsyncMock()
    mock_pipeline.zadd = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session), \
         patch("services.scheduler.scheduler.publish_message", new_callable=AsyncMock) as mock_publish:

        count = await process_due_monitors(limit=10)
        assert count == 1
        assert mock_publish.called
        assert mock_pipeline.zadd.called


@pytest.mark.asyncio
async def test_scheduler_process_due_edge_cases(db_session: AsyncSession, test_user: User):
    mock_redis = AsyncMock()
    mock_redis.eval = AsyncMock(return_value=[])

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis):
        assert await process_due_monitors() == 0

    mock_redis.eval = AsyncMock(return_value=["invalid-uuid-string"])
    mock_redis.zrem = AsyncMock()
    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis):
        assert await process_due_monitors() == 0
        mock_redis.zrem.assert_called_once_with("scheduler:monitors", "invalid-uuid-string")

    inactive_mon = Monitor(
        user_id=test_user.id,
        name="Inactive Mon",
        url="https://inactive.example.com",
        is_active=False,
    )
    db_session.add(inactive_mon)
    await db_session.commit()
    await db_session.refresh(inactive_mon)

    mock_redis.eval = AsyncMock(return_value=[str(inactive_mon.id)])
    mock_pipe = AsyncMock()
    mock_pipe.zrem = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session):
        count = await process_due_monitors()
        assert count == 1
        assert mock_pipe.zrem.called


@pytest.mark.asyncio
async def test_sync_active_monitors_to_redis(db_session: AsyncSession, test_user: User):
    monitor = Monitor(
        user_id=test_user.id,
        name="Active Sync Target",
        url="https://sync.example.com",
        is_active=True,
    )
    db_session.add(monitor)
    await db_session.commit()

    mock_redis = AsyncMock()
    mock_redis.zscore = AsyncMock(return_value=None)
    mock_pipe = AsyncMock()
    mock_pipe.zadd = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session):
        await sync_active_monitors_to_redis()
        assert mock_pipe.zadd.called
        assert mock_pipe.execute.called


@pytest.mark.asyncio
async def test_run_scheduler_loop():
    with patch("services.scheduler.scheduler.sync_active_monitors_to_redis", new_callable=AsyncMock) as mock_sync, \
         patch("services.scheduler.scheduler.process_due_monitors", new_callable=AsyncMock, return_value=0), \
         patch("services.scheduler.scheduler.asyncio.sleep", side_effect=asyncio.CancelledError):
        try:
            await run_scheduler_loop()
        except asyncio.CancelledError:
            pass
        assert mock_sync.called


@pytest.mark.asyncio
async def test_telemetry_maintenance_loop_triggers(db_session: AsyncSession):
    fake_time = datetime(2026, 9, 23, 3, 15, tzinfo=timezone.utc)
    mock_dt = MagicMock()
    mock_dt.now.return_value = fake_time

    with patch("services.scheduler.scheduler.datetime", mock_dt), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session), \
         patch("services.scheduler.scheduler.aggregate_hourly_uptime", new_callable=AsyncMock) as mock_rollup, \
         patch("services.scheduler.scheduler.purge_old_check_results", new_callable=AsyncMock) as mock_purge, \
         patch("services.scheduler.scheduler.asyncio.sleep", side_effect=asyncio.CancelledError):

        try:
            await run_telemetry_maintenance_loop()
        except asyncio.CancelledError:
            pass

        assert mock_rollup.called
        assert mock_purge.called
