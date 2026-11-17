import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from services.checker.checker import process_check_job
from services.checker.quorum_consumer import process_quorum_challenge
from services.common.config import settings
from services.common.models import Monitor, User
from services.common.rabbitmq import publish_message, setup_quorum_topology


@pytest.mark.asyncio
async def test_publish_message_with_exchange_and_expiration() -> None:
    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)

    with patch("services.common.rabbitmq.get_publish_channel", return_value=mock_channel):
        payload = {"test": "data"}
        await publish_message(
            queue_name="quorum.challenges.all",
            payload=payload,
            exchange_name="quorum.exchange",
            routing_key="challenge.all",
            expiration="20000",
        )

        assert mock_channel.declare_exchange.called
        assert mock_exchange.publish.called
        msg_arg = mock_exchange.publish.call_args[0][0]
        assert msg_arg.expiration == 20.0
        assert mock_exchange.publish.call_args[1]["routing_key"] == "challenge.all"


@pytest.mark.asyncio
async def test_setup_quorum_topology() -> None:
    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_queue = AsyncMock()
    mock_channel.declare_exchange = AsyncMock(return_value=mock_exchange)
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    queue = await setup_quorum_topology(mock_channel, region_id="vn-han")
    assert queue == mock_queue
    assert mock_channel.declare_exchange.called
    assert mock_channel.declare_queue.call_args[1]["arguments"] == {"x-message-ttl": 20000}
    assert mock_queue.bind.call_count == 2


@pytest.mark.asyncio
async def test_checker_dispatches_quorum_challenge_on_failure(db_session) -> None:
    user = User(email="checker_quorum@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="Quorum Checker Target",
        url="https://1.1.1.1/health",
        quorum_enabled=True,
        quorum_threshold=2,
        quorum_regions=["vn-han", "sg-sin", "us-iad"],
    )
    db_session.add(monitor)
    await db_session.commit()

    job_id = uuid.uuid4()
    payload = {
        "job_id": str(job_id),
        "monitor_id": str(monitor.id),
        "url": monitor.url,
        "method": "GET",
        "timeout_seconds": 10,
        "expected_status_code": 200,
        "quorum_enabled": True,
        "quorum_threshold": 2,
        "quorum_regions": ["vn-han", "sg-sin", "us-iad"],
    }

    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=False)
    mock_redis.set = AsyncMock(return_value=True)
    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)

    mock_publish = AsyncMock()

    with patch("services.checker.checker.get_redis_client", return_value=mock_redis), \
         patch("services.checker.checker.execute_check", return_value=(False, 500, 150, "Server Error", None)), \
         patch("services.checker.checker.publish_message", mock_publish), \
         patch("services.checker.checker.AsyncSessionLocal", return_value=db_session):

        result = await process_check_job(payload)
        assert result is True

        assert mock_redis.set.called
        all_set_keys = [c[0][0] for c in mock_redis.set.call_args_list]
        assert f"quorum:active:{monitor.id}" in all_set_keys

        assert pipe.hset.called
        assert pipe.expire.called
        assert pipe.execute.called

        assert mock_publish.called
        publish_kwargs = mock_publish.call_args[1]
        assert publish_kwargs.get("exchange_name") == settings.RABBITMQ_EXCHANGE_QUORUM
        assert publish_kwargs.get("routing_key") == "challenge.all"
        assert publish_kwargs.get("expiration") == "20000"


@pytest.mark.asyncio
async def test_checker_releases_lock_if_amqp_publish_fails(db_session) -> None:
    user = User(email="lock_release@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="Quorum Fail Target",
        url="https://1.1.1.1/health",
        quorum_enabled=True,
        quorum_threshold=2,
        quorum_regions=["vn-han", "sg-sin", "us-iad"],
    )
    db_session.add(monitor)
    await db_session.commit()

    job_id = uuid.uuid4()
    payload = {
        "job_id": str(job_id),
        "monitor_id": str(monitor.id),
        "url": monitor.url,
        "method": "GET",
        "timeout_seconds": 10,
        "expected_status_code": 200,
        "quorum_enabled": True,
        "quorum_threshold": 2,
        "quorum_regions": ["vn-han", "sg-sin", "us-iad"],
    }

    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=False)
    mock_redis.set = AsyncMock(return_value=True)
    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)

    mock_publish = AsyncMock(side_effect=RuntimeError("RabbitMQ Broker Disconnected"))

    with patch("services.checker.checker.get_redis_client", return_value=mock_redis), \
         patch("services.checker.checker.execute_check", return_value=(False, 502, 200, "Bad Gateway", None)), \
         patch("services.checker.checker.publish_message", mock_publish), \
         patch("services.checker.checker.AsyncSessionLocal", return_value=db_session):

        with pytest.raises(RuntimeError, match="RabbitMQ Broker Disconnected"):
            await process_check_job(payload)

        assert mock_redis.delete.called
        assert f"quorum:active:{monitor.id}" in [c[0][0] for c in mock_redis.delete.call_args_list]


@pytest.mark.asyncio
async def test_quorum_consumer_ignores_self_challenge() -> None:
    mock_redis = AsyncMock()

    payload = {
        "challenge_id": str(uuid.uuid4()),
        "monitor_id": str(uuid.uuid4()),
        "initiator_region": settings.REGION_ID,
        "url": "https://1.1.1.1/health",
        "method": "GET",
        "expected_status_code": 200,
        "timeout_seconds": 5,
        "quorum_threshold": 2,
        "quorum_regions": ["vn-han", "sg-sin", "us-iad"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    with patch("services.checker.quorum_consumer.execute_check", autospec=True) as mock_exec:
        success = await process_quorum_challenge(payload, mock_redis)
        assert success is True
        assert not mock_exec.called


@pytest.mark.asyncio
async def test_quorum_consumer_probes_and_records_vote() -> None:
    mock_redis = AsyncMock()
    pipe = MagicMock()
    pipe.execute = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=pipe)

    challenge_id = str(uuid.uuid4())
    payload = {
        "challenge_id": challenge_id,
        "monitor_id": str(uuid.uuid4()),
        "initiator_region": "sg-sin",
        "url": "https://1.1.1.1/health",
        "method": "GET",
        "expected_status_code": 200,
        "timeout_seconds": 10,
        "quorum_threshold": 2,
        "quorum_regions": ["vn-han", "sg-sin", "us-iad"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    with patch(
        "services.checker.quorum_consumer.execute_check",
        autospec=True,
        return_value=(True, 200, 48, None, 90),
    ) as mock_exec:
        success = await process_quorum_challenge(payload, mock_redis)
        assert success is True
        assert mock_exec.called

        assert mock_exec.call_args[1]["job_id"] == challenge_id
        assert mock_exec.call_args[1]["monitor_id"] == payload["monitor_id"]
        assert mock_exec.call_args[1]["expected_status_code"] == 200
        assert mock_exec.call_args[1]["timeout_seconds"] <= 5

        assert pipe.hset.called
        assert pipe.expire.called
        assert pipe.execute.called

        hset_args = pipe.hset.call_args[0]
        assert f"quorum:session:{challenge_id}" == hset_args[0]
        assert settings.REGION_ID == hset_args[1]
        vote_data = json.loads(hset_args[2])
        assert vote_data["status"] == "PASS"
        assert vote_data["status_code"] == 200
