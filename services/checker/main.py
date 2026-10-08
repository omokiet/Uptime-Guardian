import asyncio
import json
import logging
from services.checker.checker import close_httpx_client, process_check_job
from services.common.config import settings
from services.common.metrics import CHECKER_PROCESSING_ERRORS_TOTAL
from services.common.rabbitmq import close_rabbitmq, get_rabbitmq_connection
from services.common.redis_client import close_redis

logger = logging.getLogger(__name__)


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
                except Exception as exc:
                    CHECKER_PROCESSING_ERRORS_TOTAL.inc()
                    logger.error("Lỗi xử lý check job từ RabbitMQ: %s", exc, exc_info=True)


async def main() -> None:
    try:
        await run_checker_worker()
    finally:
        await close_httpx_client()
        await close_redis()
        await close_rabbitmq()


if __name__ == "__main__":
    asyncio.run(main())
