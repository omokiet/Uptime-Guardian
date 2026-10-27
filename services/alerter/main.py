import asyncio
import json
import logging
from services.alerter.state_machine import handle_alert_event
from services.common.config import settings
from services.common.rabbitmq import close_rabbitmq, get_rabbitmq_connection
from services.common.redis_client import close_redis

logger = logging.getLogger(__name__)


async def run_alerter_worker() -> None:
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)
    queue = await channel.declare_queue(settings.RABBITMQ_QUEUE_ALERT_EVENTS, durable=True)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            try:
                payload = json.loads(message.body.decode("utf-8"))
            except Exception as exc:
                logger.error("Lỗi decode alert event JSON từ RabbitMQ: %s", exc)
                async with message.process(requeue=False):
                    pass
                continue

            async with message.process(requeue=True):
                try:
                    await handle_alert_event(payload)
                except Exception as exc:
                    logger.error("Lỗi xử lý alert event từ RabbitMQ: %s", exc, exc_info=True)
                    raise


async def main() -> None:
    try:
        await run_alerter_worker()
    finally:
        await close_redis()
        await close_rabbitmq()


if __name__ == "__main__":
    asyncio.run(main())
