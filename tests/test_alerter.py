import uuid
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from services.alerter.state_machine import handle_alert_event, notify_channels, send_telegram_alert
from services.common.config import settings
from services.common.models import AlertConfig, Monitor, User


@pytest.mark.asyncio
async def test_alerter_state_machine_transitions(db_session: AsyncSession, test_user: User):
    monitor = Monitor(
        user_id=test_user.id,
        name="Critical API",
        url="https://api.example.com",
        consecutive_threshold=3,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    alert_cfg = AlertConfig(
        monitor_id=monitor.id,
        channel="telegram",
        destination="123456789",
        is_enabled=True,
    )
    db_session.add(alert_cfg)
    await db_session.commit()

    redis_hash = {}

    async def fake_hgetall(key):
        return redis_hash

    async def fake_hset(key, mapping):
        redis_hash.update(mapping)

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()
    mock_redis.hgetall = AsyncMock(side_effect=fake_hgetall)
    mock_redis.hset = AsyncMock(side_effect=fake_hset)

    with patch("services.alerter.state_machine.get_redis_client", return_value=mock_redis), \
         patch("services.alerter.state_machine.AsyncSessionLocal", return_value=db_session), \
         patch("services.alerter.state_machine.send_telegram_alert", new_callable=AsyncMock) as mock_tg:

        event_fail = {
            "monitor_id": str(monitor.id),
            "is_success": False,
            "error_message": "Gateway Timeout 504",
            "url": monitor.url,
        }

        await handle_alert_event(event_fail)
        assert redis_hash["status"] == "PENDING_DOWN"
        assert redis_hash["consecutive_fails"] == "1"
        assert mock_tg.call_count == 0

        await handle_alert_event(event_fail)
        assert redis_hash["status"] == "PENDING_DOWN"
        assert redis_hash["consecutive_fails"] == "2"
        assert mock_tg.call_count == 0

        await handle_alert_event(event_fail)
        assert redis_hash["status"] == "DOWN"
        assert redis_hash["consecutive_fails"] == "3"
        assert mock_tg.call_count == 1

        await handle_alert_event(event_fail)
        assert redis_hash["status"] == "DOWN"
        assert mock_tg.call_count == 1

        event_success = {
            "monitor_id": str(monitor.id),
            "is_success": True,
            "url": monitor.url,
        }
        await handle_alert_event(event_success)
        assert redis_hash["status"] == "UP"
        assert redis_hash["consecutive_fails"] == "0"
        assert mock_tg.call_count == 2


@pytest.mark.asyncio
async def test_send_telegram_alert_scenarios():
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", ""):
        assert await send_telegram_alert("123", "msg") is False

    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "valid_token"):
        assert await send_telegram_alert("", "msg") is False

        mock_resp_200 = httpx.Response(200, request=httpx.Request("POST", "https://api.telegram.org"))
        with patch("httpx.AsyncClient.post", return_value=mock_resp_200):
            assert await send_telegram_alert("123", "msg") is True

        mock_resp_500 = httpx.Response(500, request=httpx.Request("POST", "https://api.telegram.org"))
        with patch("httpx.AsyncClient.post", return_value=mock_resp_500):
            assert await send_telegram_alert("123", "msg") is False

        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Network error")):
            assert await send_telegram_alert("123", "msg") is False


@pytest.mark.asyncio
async def test_notify_channels_fallback(db_session: AsyncSession):
    with patch("services.alerter.state_machine.AsyncSessionLocal", return_value=db_session), \
         patch.object(settings, "TELEGRAM_DEFAULT_CHAT_ID", "default_999"), \
         patch("services.alerter.state_machine.send_telegram_alert", new_callable=AsyncMock) as mock_send:
        await notify_channels(uuid.uuid4(), "Fallback Mon", "Test alert")
        mock_send.assert_called_once_with("default_999", "Test alert")


@pytest.mark.asyncio
async def test_handle_alert_event_edge_cases():
    await handle_alert_event({})

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=False)
    with patch("services.alerter.state_machine.get_redis_client", return_value=mock_redis), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await handle_alert_event({"monitor_id": str(uuid.uuid4())})
