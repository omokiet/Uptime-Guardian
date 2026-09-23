import asyncio
from services.common.rabbitmq import close_rabbitmq
from services.common.redis_client import close_redis
from services.scheduler.scheduler import (
    run_scheduler_loop,
    run_telemetry_maintenance_loop,
)


async def main() -> None:
    try:
        await asyncio.gather(
            run_scheduler_loop(),
            run_telemetry_maintenance_loop(),
        )
    finally:
        await close_redis()
        await close_rabbitmq()


if __name__ == "__main__":
    asyncio.run(main())
