import asyncio
import json
import aio_pika
from services.checker.checker import process_check_job
from services.common.config import settings
from services.common.rabbitmq import close_rabbitmq, get_rabbitmq_connection
from services.common.redis_client import close_redis


async def run_checker_worker() -> None:
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)
    queue = await channel.declare_queue(settings.RABBITMQ_QUEUE_CHECK_JOBS, durable=True)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process(requeue=False):
                try:
                    payload = json.loads(message.body.decode("utf-8"))
                    await process_check_job(payload)
                except Exception:
                    pass


async def main() -> None:
    try:
        await run_checker_worker()
    finally:
        await close_redis()
        await close_rabbitmq()


if __name__ == "__main__":
    asyncio.run(main())
