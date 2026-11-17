import json
import uuid
from unittest.mock import AsyncMock, patch
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from services.api_gateway.main import app
from services.api_gateway.routers.websocket import ConnectionManager, manager
from services.checker.checker import process_check_job
from services.alerter.state_machine import handle_alert_event
from services.common.models import Monitor, User
from services.common.security import create_access_token
from sqlalchemy.ext.asyncio import AsyncSession


def test_websocket_rejects_missing_token() -> None:
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/telemetry") as websocket:
            websocket.send_text(json.dumps({"action": "not_auth"}))
            websocket.receive_text()
    assert exc_info.value.code == 1008


def test_websocket_rejects_invalid_token() -> None:
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/telemetry?token=bad.invalid.jwt") as websocket:
            websocket.receive_text()
    assert exc_info.value.code == 1008


def test_websocket_authenticates_via_query_token() -> None:
    user_id = str(uuid.uuid4())
    token = create_access_token({"sub": user_id})
    client = TestClient(app)

    with patch.object(manager, "_redis_listener", new_callable=AsyncMock):
        with client.websocket_connect(f"/ws/telemetry?token={token}") as websocket:
            frame = websocket.receive_json()
            assert frame["event"] == "connected"
            assert frame["user_id"] == user_id

            websocket.send_text(json.dumps({"action": "ping"}))
            pong_frame = websocket.receive_json()
            assert pong_frame["event"] == "pong"


def test_websocket_authenticates_via_initial_frame() -> None:
    user_id = str(uuid.uuid4())
    token = create_access_token({"sub": user_id})
    client = TestClient(app)

    with patch.object(manager, "_redis_listener", new_callable=AsyncMock):
        with client.websocket_connect("/ws/telemetry") as websocket:
            websocket.send_text(json.dumps({"action": "auth", "token": token}))
            frame = websocket.receive_json()
            assert frame["event"] == "connected"
            assert frame["user_id"] == user_id


@pytest.mark.asyncio
async def test_connection_manager_drop_oldest_on_queue_overflow() -> None:
    custom_manager = ConnectionManager()
    user_id = str(uuid.uuid4())
    mock_ws = AsyncMock()

    with patch.object(custom_manager, "_redis_listener", new_callable=AsyncMock):
        await custom_manager.connect(mock_ws, user_id)

    queue = custom_manager.socket_queues[mock_ws]
    # Fill queue to maximum capacity of 100 items
    for i in range(100):
        await custom_manager.broadcast_to_user(user_id, {"seq": i})

    assert queue.full() is True

    # 101st message triggers drop_oldest policy
    await custom_manager.broadcast_to_user(user_id, {"seq": 100})
    assert queue.qsize() == 100

    first_item = queue.get_nowait()
    # The 0th message was dropped, first item is seq 1
    assert first_item["seq"] == 1

    await custom_manager.disconnect(mock_ws, user_id)
    assert user_id not in custom_manager.active_connections


@pytest.mark.asyncio
async def test_checker_publishes_telemetry_to_redis(db_session: AsyncSession, test_user: User) -> None:
    monitor = Monitor(
        user_id=test_user.id,
        name="Telemetry Target",
        url="https://api.example.com/health",
        expected_status_code=200,
    )
    db_session.add(monitor)
    await db_session.commit()

    job_id = str(uuid.uuid4())
    payload = {
        "job_id": job_id,
        "monitor_id": str(monitor.id),
        "user_id": str(test_user.id),
        "url": monitor.url,
        "expected_status_code": 200,
    }

    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=False)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()
    mock_redis.publish = AsyncMock()

    fake_addr = [(None, None, None, None, ("93.184.216.34", 80))]

    with patch("services.checker.checker.get_redis_client", return_value=mock_redis), \
         patch("services.checker.checker.AsyncSessionLocal", return_value=db_session), \
         patch("services.checker.checker.publish_message", new_callable=AsyncMock), \
         patch("services.checker.checker.execute_check", return_value=(True, 200, 45, None, 90)), \
         patch("socket.getaddrinfo", return_value=fake_addr):

        await process_check_job(payload)

        assert mock_redis.publish.called
        channel_name, raw_payload = mock_redis.publish.call_args[0]
        assert channel_name == f"telemetry:user:{test_user.id}"
        event_dict = json.loads(raw_payload)
        assert event_dict["event"] == "check_result"
        assert event_dict["data"]["monitor_id"] == str(monitor.id)
        assert event_dict["data"]["response_time_ms"] == 45
        assert event_dict["data"]["is_success"] is True


@pytest.mark.asyncio
async def test_alerter_publishes_status_change_to_redis(db_session: AsyncSession) -> None:
    user = User(email="fsm_ws@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    monitor = Monitor(
        user_id=user.id,
        name="FSM WS Target",
        url="https://1.1.1.1/health",
        consecutive_threshold=1,
        current_status="UP",
    )
    db_session.add(monitor)
    await db_session.commit()

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.eval = AsyncMock(return_value=1)
    mock_redis.publish = AsyncMock()
    mock_redis.hgetall = AsyncMock(return_value={
        "status": "UP",
        "consecutive_fails": "0",
        "cooldown_until": "0",
    })

    event = {
        "job_id": str(uuid.uuid4()),
        "monitor_id": str(monitor.id),
        "url": monitor.url,
        "is_success": False,
        "error_message": "Connection refused",
    }

    mock_notify = AsyncMock()
    with patch("services.alerter.state_machine.get_redis_client", return_value=mock_redis), \
         patch("services.alerter.state_machine.notify_channels", mock_notify), \
         patch("services.alerter.state_machine.AsyncSessionLocal", return_value=db_session):

        await handle_alert_event(event)

        assert mock_redis.publish.called
        channel_name, raw_payload = mock_redis.publish.call_args[0]
        assert channel_name == f"telemetry:user:{user.id}"
        event_dict = json.loads(raw_payload)
        assert event_dict["event"] == "status_change"
        assert event_dict["data"]["previous_status"] == "UP"
        assert event_dict["data"]["new_status"] == "DOWN"
        assert event_dict["data"]["reason"] == "Connection refused"
