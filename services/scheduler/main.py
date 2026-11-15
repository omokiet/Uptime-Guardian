import asyncio
import prometheus_client
from services.common.rabbitmq import close_rabbitmq
from services.common.redis_client import close_redis
from services.scheduler.scheduler import (
    run_reconciliation_loop,
    run_scheduler_loop,
    run_telemetry_maintenance_loop,
)


def start_metrics_server(port: int = 8002) -> None:
    try:
        prometheus_client.start_http_server(port)
    except OSError:
        pass


async def main() -> None:
    start_metrics_server(8002)
    try:
        await asyncio.gather(
            run_scheduler_loop(),
            run_telemetry_maintenance_loop(),
            run_reconciliation_loop(),
        )
    finally:
        await close_redis()
        await close_rabbitmq()


if __name__ == "__main__":
    asyncio.run(main())
