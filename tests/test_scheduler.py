import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import Monitor, User
from services.scheduler.scheduler import (
    process_due_monitors,
    reconcile_monitors_with_redis,
    run_reconciliation_loop,
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
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with patch("services.scheduler.scheduler.datetime", mock_dt), \
         patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
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
        assert mock_redis.set.called


@pytest.mark.asyncio
async def test_telemetry_maintenance_loop_lock_skipped(db_session: AsyncSession):
    fake_time = datetime(2026, 9, 23, 3, 15, tzinfo=timezone.utc)
    mock_dt = MagicMock()
    mock_dt.now.return_value = fake_time
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=False)

    with patch("services.scheduler.scheduler.datetime", mock_dt), \
         patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session), \
         patch("services.scheduler.scheduler.aggregate_hourly_uptime", new_callable=AsyncMock) as mock_rollup, \
         patch("services.scheduler.scheduler.purge_old_check_results", new_callable=AsyncMock) as mock_purge, \
         patch("services.scheduler.scheduler.asyncio.sleep", side_effect=asyncio.CancelledError):

        try:
            await run_telemetry_maintenance_loop()
        except asyncio.CancelledError:
            pass

        assert not mock_rollup.called
        assert not mock_purge.called


@pytest.mark.asyncio
async def test_reconcile_monitors_adds_missing_and_removes_orphans(db_session: AsyncSession, test_user: User):
    m_active1 = Monitor(user_id=test_user.id, name="Active 1", url="https://m1.com", is_active=True)
    m_active2 = Monitor(user_id=test_user.id, name="Active 2", url="https://m2.com", is_active=True)
    m_inactive = Monitor(user_id=test_user.id, name="Inactive", url="https://m3.com", is_active=False)
    db_session.add_all([m_active1, m_active2, m_inactive])
    await db_session.commit()

    orphan_id = "00000000-0000-0000-0000-000000000099"
    redis_members = [str(m_active2.id), orphan_id]

    mock_redis = AsyncMock()
    mock_redis.zrange = AsyncMock(return_value=redis_members)
    mock_pipe = AsyncMock()
    mock_pipe.zadd = MagicMock()
    mock_pipe.zrem = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session):
        added, removed = await reconcile_monitors_with_redis()
        assert added == 1
        assert removed == 1
        mock_pipe.zadd.assert_called_once()
        args, kwargs = mock_pipe.zadd.call_args
        assert args[0] == "scheduler:monitors"
        assert str(m_active1.id) in args[1]
        assert kwargs.get("nx") is True
        mock_pipe.zrem.assert_called_once_with("scheduler:monitors", orphan_id)
        assert mock_pipe.execute.called


@pytest.mark.asyncio
async def test_reconcile_monitors_empty_diff(db_session: AsyncSession, test_user: User):
    m_active = Monitor(user_id=test_user.id, name="In Sync", url="https://sync.com", is_active=True)
    db_session.add(m_active)
    await db_session.commit()

    mock_redis = AsyncMock()
    mock_redis.zrange = AsyncMock(return_value=[str(m_active.id)])
    mock_pipe = AsyncMock()
    mock_pipe.zadd = MagicMock()
    mock_pipe.zrem = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session):
        added, removed = await reconcile_monitors_with_redis()
        assert added == 0
        assert removed == 0
        assert not mock_pipe.zadd.called
        assert not mock_pipe.zrem.called


@pytest.mark.asyncio
async def test_run_reconciliation_loop_with_lock():
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(side_effect=[True, False])

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.reconcile_monitors_with_redis", new_callable=AsyncMock) as mock_rec, \
         patch("services.scheduler.scheduler.asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
        try:
            await run_reconciliation_loop(interval_seconds=1)
        except asyncio.CancelledError:
            pass
        assert mock_rec.call_count == 1


@pytest.mark.asyncio
async def test_run_reconciliation_loop_fault_injection_recovery():
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.reconcile_monitors_with_redis", side_effect=RuntimeError("DB drop")), \
         patch("services.scheduler.scheduler.asyncio.sleep", side_effect=asyncio.CancelledError):
        try:
            await run_reconciliation_loop(interval_seconds=1)
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_scheduler_batch_publish_partial_failure_retains_lease(db_session: AsyncSession, test_user: User):
    m1 = Monitor(
        user_id=test_user.id,
        name="Batch M1",
        url="https://m1.example.com",
        interval_seconds=30,
        is_active=True,
    )
    m2 = Monitor(
        user_id=test_user.id,
        name="Batch M2",
        url="https://m2.example.com",
        interval_seconds=60,
        is_active=True,
    )
    db_session.add_all([m1, m2])
    await db_session.commit()
    await db_session.refresh(m1)
    await db_session.refresh(m2)

    mock_redis = AsyncMock()
    mock_redis.eval = AsyncMock(return_value=[str(m1.id), str(m2.id)])
    mock_pipe = AsyncMock()
    mock_pipe.zadd = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    async def mock_publish(queue_name, payload):
        if payload["monitor_id"] == str(m1.id):
            raise RuntimeError("AMQP connection reset by peer")
        return None

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session), \
         patch("services.scheduler.scheduler.publish_message", side_effect=mock_publish):

        count = await process_due_monitors(limit=10)
        assert count == 2

        # m1 failed to publish -> its score must NOT be updated (keeps 60s lease for retry)
        # m2 succeeded -> its score must be updated
        assert mock_pipe.zadd.call_count == 1
        zadd_call_args = mock_pipe.zadd.call_args[0]
        assert str(m2.id) in zadd_call_args[1]
        assert str(m1.id) not in zadd_call_args[1]


@pytest.mark.asyncio
async def test_scheduler_excludes_soft_deleted_monitors(db_session: AsyncSession, test_user: User):
    m_active = Monitor(
        user_id=test_user.id,
        name="Active Mon",
        url="https://active.example.com",
        is_active=True,
        deleted_at=None,
    )
    m_deleted = Monitor(
        user_id=test_user.id,
        name="Soft Deleted Mon",
        url="https://deleted.example.com",
        is_active=True,
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add_all([m_active, m_deleted])
    await db_session.commit()
    await db_session.refresh(m_active)
    await db_session.refresh(m_deleted)

    # 1. sync_active_monitors_to_redis must skip soft-deleted
    mock_redis = AsyncMock()
    mock_pipe = AsyncMock()
    mock_pipe.zadd = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session):

        await sync_active_monitors_to_redis()
        assert mock_pipe.zadd.call_count == 1
        zadd_args = mock_pipe.zadd.call_args[0][1]
        assert str(m_active.id) in zadd_args
        assert str(m_deleted.id) not in zadd_args

    # 2. process_due_monitors must purge soft-deleted monitor from Redis and not publish
    mock_redis_due = AsyncMock()
    mock_redis_due.eval = AsyncMock(return_value=[str(m_deleted.id)])
    mock_pipe_due = AsyncMock()
    mock_pipe_due.zrem = MagicMock()
    mock_redis_due.pipeline = MagicMock(return_value=mock_pipe_due)

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis_due), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session), \
         patch("services.scheduler.scheduler.publish_message", new_callable=AsyncMock) as mock_pub:

        count = await process_due_monitors(limit=10)
        assert count == 1
        assert not mock_pub.called
        mock_pipe_due.zrem.assert_called_once_with("scheduler:monitors", str(m_deleted.id))

    # 3. reconcile_monitors_with_redis must treat soft-deleted as not active
    mock_redis_rec = AsyncMock()
    mock_redis_rec.zrange = AsyncMock(return_value=[str(m_active.id), str(m_deleted.id)])
    mock_pipe_rec = AsyncMock()
    mock_pipe_rec.zrem = MagicMock()
    mock_redis_rec.pipeline = MagicMock(return_value=mock_pipe_rec)

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis_rec), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session):

        added, removed = await reconcile_monitors_with_redis()
        assert added == 0
        assert removed == 1
        mock_pipe_rec.zrem.assert_called_once_with("scheduler:monitors", str(m_deleted.id))
