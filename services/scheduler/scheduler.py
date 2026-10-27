import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import List
from sqlalchemy import select
from services.common.config import settings
from services.common.database import AsyncSessionLocal
from services.common.metrics import (
    SCHEDULER_DISPATCHED_JOBS_TOTAL,
    SCHEDULER_MAINTENANCE_ERRORS_TOTAL,
)
from services.common.models import Monitor
from services.common.rabbitmq import publish_message
from services.common.partitions import ensure_future_partitions
from services.common.redis_client import get_redis_client
from services.common.rollup import (
    aggregate_hourly_uptime,
    backfill_missing_hourly_summaries,
    purge_old_check_results,
)

logger = logging.getLogger(__name__)

# Atomic Lua script: fetch items <= now_ms and lease them ahead
# to prevent race conditions across multiple scheduler replicas
LUA_SCHEDULE_POP = """
local key = KEYS[1]
local max_score = tonumber(ARGV[1])
local lease_score = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

local members = redis.call('ZRANGEBYSCORE', key, '-inf', max_score, 'LIMIT', 0, limit)
for _, member in ipairs(members) do
    redis.call('ZADD', key, lease_score, member)
end
return members
"""


async def sync_active_monitors_to_redis() -> None:
    redis_client = get_redis_client()
    now_ms = int(time.time() * 1000)

    async with AsyncSessionLocal() as session:
        stmt = select(Monitor).where(Monitor.is_active.is_(True))
        result = await session.execute(stmt)
        monitors = result.scalars().all()

        pipe = redis_client.pipeline()
        for monitor in monitors:
            pipe.zadd("scheduler:monitors", {str(monitor.id): now_ms}, nx=True)
        await pipe.execute()


async def process_due_monitors(limit: int = 100) -> int:
    redis_client = get_redis_client()
    now_ms = int(time.time() * 1000)
    lease_score = now_ms + 60000

    due_monitor_ids: List[str] = await redis_client.eval(
        LUA_SCHEDULE_POP,
        1,
        "scheduler:monitors",
        now_ms,
        lease_score,
        limit,
    )

    if not due_monitor_ids:
        return 0

    parsed_ids = []
    for m_id in due_monitor_ids:
        try:
            parsed_ids.append(uuid.UUID(m_id))
        except ValueError:
            await redis_client.zrem("scheduler:monitors", m_id)

    if not parsed_ids:
        return 0

    async with AsyncSessionLocal() as session:
        stmt = select(Monitor).where(Monitor.id.in_(parsed_ids))
        result = await session.execute(stmt)
        monitors_map = {m.id: m for m in result.scalars().all()}

    pipe = redis_client.pipeline()
    for monitor_id in parsed_ids:
        monitor = monitors_map.get(monitor_id)

        if not monitor or not monitor.is_active:
            pipe.zrem("scheduler:monitors", str(monitor_id))
            continue

        job_id = uuid.uuid4()
        next_score = now_ms + (monitor.interval_seconds * 1000)
        pipe.zadd("scheduler:monitors", {str(monitor.id): next_score})

        payload = {
            "job_id": str(job_id),
            "monitor_id": str(monitor.id),
            "url": monitor.url,
            "method": monitor.method,
            "timeout_seconds": monitor.timeout_seconds,
            "expected_status_code": monitor.expected_status_code,
        }
        await publish_message(settings.RABBITMQ_QUEUE_CHECK_JOBS, payload)
        SCHEDULER_DISPATCHED_JOBS_TOTAL.inc()

    await pipe.execute()
    return len(parsed_ids)


async def run_scheduler_loop() -> None:
    await sync_active_monitors_to_redis()
    while True:
        try:
            count = await process_due_monitors()
            if count == 0:
                await asyncio.sleep(1)
        except Exception:
            await asyncio.sleep(1)


async def run_telemetry_maintenance_loop() -> None:
    redis_client = get_redis_client()

    try:
        async with AsyncSessionLocal() as session:
            await ensure_future_partitions(session, weeks_ahead=4)
            await backfill_missing_hourly_summaries(session, hours=24)
    except Exception as exc:
        logger.warning("Startup maintenance tasks failed: %s", exc)

    while True:
        try:
            now = datetime.now(timezone.utc)
            if now.minute >= 5:
                rollup_lock_key = f"lock:maintenance:rollup:{now.strftime('%Y%m%d%H')}"
                if await redis_client.set(rollup_lock_key, "1", nx=True, ex=3600):
                    async with AsyncSessionLocal() as session:
                        await aggregate_hourly_uptime(session)
                        await backfill_missing_hourly_summaries(session, hours=24)

            if now.hour == 3 and now.minute >= 10:
                retention_lock_key = f"lock:maintenance:retention:{now.strftime('%Y%m%d')}"
                if await redis_client.set(retention_lock_key, "1", nx=True, ex=86400):
                    async with AsyncSessionLocal() as session:
                        await ensure_future_partitions(session, weeks_ahead=4)
                        await purge_old_check_results(session, retention_days=7)
        except Exception as exc:
            logger.error("Telemetry maintenance loop failed: %s", exc, exc_info=True)
            SCHEDULER_MAINTENANCE_ERRORS_TOTAL.labels(task="maintenance_loop").inc()

        await asyncio.sleep(30)


async def reconcile_monitors_with_redis() -> tuple[int, int]:
    redis_client = get_redis_client()
    now_ms = int(time.time() * 1000)

    async with AsyncSessionLocal() as session:
        stmt = select(Monitor.id).where(Monitor.is_active.is_(True))
        result = await session.execute(stmt)
        active_ids = {str(m_id) for m_id in result.scalars().all()}

    redis_members = await redis_client.zrange("scheduler:monitors", 0, -1)
    redis_ids = set(redis_members)

    missing_in_redis = active_ids - redis_ids
    orphans_in_redis = redis_ids - active_ids

    if not missing_in_redis and not orphans_in_redis:
        return 0, 0

    pipe = redis_client.pipeline()

    if missing_in_redis:
        zadd_mapping = {m_id: now_ms for m_id in missing_in_redis}
        pipe.zadd("scheduler:monitors", zadd_mapping, nx=True)

    if orphans_in_redis:
        pipe.zrem("scheduler:monitors", *orphans_in_redis)

    await pipe.execute()
    return len(missing_in_redis), len(orphans_in_redis)


async def run_reconciliation_loop(interval_seconds: int = 300) -> None:
    redis_client = get_redis_client()
    lock_key = "lock:scheduler:reconciliation"

    while True:
        try:
            lock_acquired = await redis_client.set(
                lock_key,
                "1",
                nx=True,
                ex=max(interval_seconds - 10, 10),
            )
            if lock_acquired:
                added, removed = await reconcile_monitors_with_redis()
                if added > 0 or removed > 0:
                    logger.info("Reconciliation completed: +%d added, -%d removed", added, removed)
        except Exception as exc:
            logger.error("Reconciliation loop failed: %s", exc, exc_info=True)
            SCHEDULER_MAINTENANCE_ERRORS_TOTAL.labels(task="reconciliation").inc()

        await asyncio.sleep(interval_seconds)
