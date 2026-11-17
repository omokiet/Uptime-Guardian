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


async def publish_message(
    queue_name: str,
    payload: Dict[str, Any],
    exchange_name: Optional[str] = None,
    routing_key: Optional[str] = None,
    expiration: Optional[str] = None,
) -> None:
    channel = await get_publish_channel()
    message_bytes = json.dumps(payload, default=str).encode("utf-8")

    exp_val: Optional[float] = None
    if expiration:
        try:
            exp_val = float(expiration) / 1000.0
        except ValueError:
            pass

    message = aio_pika.Message(
        body=message_bytes,
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        content_type="application/json",
        expiration=exp_val,
    )

    if exchange_name:
        exchange = await channel.declare_exchange(
            exchange_name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        await exchange.publish(
            message,
            routing_key=routing_key or queue_name,
        )
    else:
        if queue_name not in _declared_queues:
            await channel.declare_queue(queue_name, durable=True)
            _declared_queues.add(queue_name)
        await channel.default_exchange.publish(
            message,
            routing_key=queue_name,
        )


async def setup_quorum_topology(
    channel: aio_pika.abc.AbstractChannel,
    region_id: str,
) -> aio_pika.abc.AbstractQueue:
    exchange = await channel.declare_exchange(
        settings.RABBITMQ_EXCHANGE_QUORUM,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )
    queue_name = f"{settings.RABBITMQ_QUEUE_QUORUM_PREFIX}.{region_id}"
    queue = await channel.declare_queue(
        queue_name,
        durable=True,
        arguments={"x-message-ttl": 20000},
    )
    await queue.bind(exchange, routing_key=f"challenge.{region_id}")
    await queue.bind(exchange, routing_key="challenge.all")
    return queue


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
