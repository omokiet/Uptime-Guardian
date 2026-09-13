import json
from typing import Any, Dict, Optional
import aio_pika
from services.common.config import settings

_robust_connection: Optional[aio_pika.abc.AbstractRobustConnection] = None


async def get_rabbitmq_connection() -> aio_pika.abc.AbstractRobustConnection:
    global _robust_connection
    if _robust_connection is None or _robust_connection.is_closed:
        _robust_connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    return _robust_connection


async def publish_message(queue_name: str, payload: Dict[str, Any]) -> None:
    connection = await get_rabbitmq_connection()
    async with connection.channel() as channel:
        await channel.declare_queue(queue_name, durable=True)
        message_bytes = json.dumps(payload, default=str).encode("utf-8")
        message = aio_pika.Message(
            body=message_bytes,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
        )
        await channel.default_exchange.publish(
            message,
            routing_key=queue_name,
        )


async def close_rabbitmq() -> None:
    global _robust_connection
    if _robust_connection is not None and not _robust_connection.is_closed:
        await _robust_connection.close()
        _robust_connection = None
