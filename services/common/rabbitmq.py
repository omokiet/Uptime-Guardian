import json
from typing import Any, Dict, Optional, Set
import aio_pika
from services.common.config import settings

_robust_connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
_publish_channel: Optional[aio_pika.abc.AbstractChannel] = None
_declared_queues: Set[str] = set()


async def get_rabbitmq_connection() -> aio_pika.abc.AbstractRobustConnection:
    global _robust_connection
    if _robust_connection is None or _robust_connection.is_closed:
        _robust_connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    return _robust_connection


async def get_publish_channel() -> aio_pika.abc.AbstractChannel:
    global _publish_channel
    if _publish_channel is None or _publish_channel.is_closed:
        connection = await get_rabbitmq_connection()
        ch = connection.channel()
        if hasattr(ch, "__aenter__"):
            _publish_channel = await ch.__aenter__()
        else:
            _publish_channel = await ch
    return _publish_channel


async def publish_message(queue_name: str, payload: Dict[str, Any]) -> None:
    channel = await get_publish_channel()
    if queue_name not in _declared_queues:
        await channel.declare_queue(queue_name, durable=True)
        _declared_queues.add(queue_name)

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
    global _robust_connection, _publish_channel
    if _publish_channel is not None and not _publish_channel.is_closed:
        if hasattr(_publish_channel, "__aexit__"):
            await _publish_channel.__aexit__(None, None, None)
        else:
            await _publish_channel.close()
        _publish_channel = None
    _declared_queues.clear()
    if _robust_connection is not None and not _robust_connection.is_closed:
        await _robust_connection.close()
        _robust_connection = None
