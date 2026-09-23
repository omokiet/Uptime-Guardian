import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import select
from services.common.config import settings
from services.common.database import AsyncSessionLocal
from services.common.metrics import SCHEDULER_DISPATCHED_JOBS_TOTAL
from services.common.models import Monitor
from services.common.rabbitmq import publish_message
from services.common.redis_client import get_redis_client
from services.common.rollup import aggregate_hourly_uptime, purge_old_check_results

# Atomic Lua script: fetch items <= now_ms and lease them ahead to prevent race condition across multiple scheduler replicas
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
        stmt = select(Monitor).where(Monitor.is_active == True)
        result = await session.execute(stmt)
        monitors = result.scalars().all()

        pipe = redis_client.pipeline()
        for monitor in monitors:
            score = await redis_client.zscore("scheduler:monitors", str(monitor.id))
            if score is None:
                pipe.zadd("scheduler:monitors", {str(monitor.id): now_ms})
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
    last_rollup_hour: Optional[int] = None
    last_retention_day: Optional[int] = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            if now.minute >= 5 and last_rollup_hour != now.hour:
                async with AsyncSessionLocal() as session:
                    await aggregate_hourly_uptime(session)
                last_rollup_hour = now.hour

            if now.hour == 3 and now.minute >= 10 and last_retention_day != now.day:
                async with AsyncSessionLocal() as session:
                    await purge_old_check_results(session, retention_days=7)
                last_retention_day = now.day
        except Exception:
            pass

        await asyncio.sleep(30)
