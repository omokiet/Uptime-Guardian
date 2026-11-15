import asyncio
import json
import logging
import prometheus_client
from services.checker.checker import close_httpx_client, process_check_job
from services.common.config import settings
from services.common.metrics import CHECKER_PROCESSING_ERRORS_TOTAL
from services.common.rabbitmq import close_rabbitmq, get_rabbitmq_connection
from services.common.redis_client import close_redis

logger = logging.getLogger(__name__)


def start_metrics_server(port: int = 8001) -> None:
    try:
        prometheus_client.start_http_server(port)
    except OSError:
        pass


async def run_checker_worker() -> None:
    connection = await get_rabbitmq_connection()
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)
    queue = await channel.declare_queue(settings.RABBITMQ_QUEUE_CHECK_JOBS, durable=True)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            try:
                payload = json.loads(message.body.decode("utf-8"))
            except Exception as exc:
                CHECKER_PROCESSING_ERRORS_TOTAL.inc()
                logger.error("Poison message JSON decode failed: %s", exc)
                async with message.process(requeue=False):
                    pass
                continue

            async with message.process(requeue=True):
                try:
                    await process_check_job(payload)
                except Exception as exc:
                    CHECKER_PROCESSING_ERRORS_TOTAL.inc()
                    logger.error("Transient error processing check job: %s", exc, exc_info=True)
                    raise


async def main() -> None:
    start_metrics_server(8001)
    try:
        await run_checker_worker()
    finally:
        await close_httpx_client()
        await close_redis()
        await close_rabbitmq()


if __name__ == "__main__":
    asyncio.run(main())
