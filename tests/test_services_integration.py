import datetime
import os
import uuid
import aio_pika
import pytest
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from services.common.config import settings
from services.common.partitions import drop_expired_partitions, ensure_future_partitions

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "true",
    reason="Requires live services. Set RUN_INTEGRATION_TESTS=true to run.",
)


@pytest.mark.asyncio
async def test_real_redis_sorted_set_and_lua_atomic():
    client = aioredis.from_url(settings.REDIS_URL)
    test_key = f"test:zset:{uuid.uuid4()}"
    try:
        now_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
        item_id = str(uuid.uuid4())

        await client.zadd(test_key, {item_id: now_ms})
        assert await client.zcard(test_key) == 1

        lua_lease = """
        local ready = redis.call('zrangebyscore', KEYS[1], 0, ARGV[1])
        if #ready > 0 then
            redis.call('zrem', KEYS[1], ready[1])
            return ready[1]
        end
        return nil
        """
        leased = await client.eval(lua_lease, 1, test_key, str(now_ms + 1000))
        assert (leased.decode("utf-8") if isinstance(leased, bytes) else leased) == item_id
        assert await client.zcard(test_key) == 0
    finally:
        await client.delete(test_key)
        await client.aclose()


@pytest.mark.asyncio
async def test_real_postgres_declarative_partitioning():
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        bind = session.get_bind()
        assert bind.dialect.name == "postgresql"

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        created_partitions = await ensure_future_partitions(session, weeks_ahead=2, current_time=now_utc)
        assert len(created_partitions) >= 2
        assert "check_results_default" in created_partitions

        stmt = text(
            "SELECT tablename FROM pg_tables "
            "WHERE tablename LIKE 'check_results_%' AND schemaname = 'public';"
        )
        result = await session.execute(stmt)
        existing_tables = set(result.scalars().all())
        assert "check_results_default" in existing_tables

        old_time = now_utc - datetime.timedelta(days=30)
        await ensure_future_partitions(session, weeks_ahead=0, current_time=old_time)
        dropped = await drop_expired_partitions(session, retention_days=7, current_time=now_utc)
        assert len(dropped) >= 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_real_rabbitmq_publish_and_requeue():
    conn = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    channel = await conn.channel()
    queue_name = f"test.queue.{uuid.uuid4()}"
    queue = await channel.declare_queue(queue_name, auto_delete=True)

    try:
        payload = b"{\"action\":\"test_service_containers\"}"
        msg = aio_pika.Message(
            body=payload,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
        )
        await channel.default_exchange.publish(msg, routing_key=queue_name)

        incoming = await queue.get(timeout=3.0)
        assert incoming.body == payload
        await incoming.reject(requeue=True)

        re_incoming = await queue.get(timeout=3.0)
        assert re_incoming.body == payload
        await re_incoming.ack()

        assert (await queue.declare()).message_count == 0
    finally:
        await queue.delete(if_empty=False)
        await channel.close()
        await conn.close()
