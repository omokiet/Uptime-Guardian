import asyncio
import json
from services.alerter.state_machine import handle_alert_event
from services.common.config import settings
from services.common.rabbitmq import close_rabbitmq, get_rabbitmq_connection
from services.common.redis_client import close_redis


async def run_alerter_worker() -> None:
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)
    queue = await channel.declare_queue(settings.RABBITMQ_QUEUE_ALERT_EVENTS, durable=True)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process(requeue=False):
                try:
                    payload = json.loads(message.body.decode("utf-8"))
                    await handle_alert_event(payload)
                except Exception:
                    pass


async def main() -> None:
    try:
        await run_alerter_worker()
    finally:
        await close_redis()
        await close_rabbitmq()


if __name__ == "__main__":
    asyncio.run(main())
