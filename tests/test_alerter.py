import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from services.alerter.main import main as alerter_main
from services.alerter.notifiers import (
    DiscordNotifier,
    EmailNotifier,
    TelegramNotifier,
    WebhookNotifier,
    get_notifier,
    send_notification,
)
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
    await handle_alert_event({"monitor_id": "not-a-valid-uuid"})

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=False)
    with patch("services.alerter.state_machine.get_redis_client", return_value=mock_redis), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(TimeoutError, match="Could not acquire alert lock"):
            await handle_alert_event({"monitor_id": str(uuid.uuid4())})


@pytest.mark.asyncio
async def test_alerter_worker_and_main():
    class DummyMessage:
        def __init__(self, body: bytes):
            self.body = body

        def process(self, requeue: bool = False):
            class _Ctx:
                async def __aenter__(s):
                    return None

                async def __aexit__(s, *args):
                    return None

            return _Ctx()

    class DummyQueue:
        def iterator(self):
            class _Iter:
                async def __aenter__(s):
                    return s

                async def __aexit__(s, *args):
                    return None

                def __aiter__(s):
                    s._items = [
                        DummyMessage(b'{"monitor_id": "test"}'),
                        DummyMessage(b"invalid-json"),
                    ]
                    return s

                async def __anext__(s):
                    if s._items:
                        return s._items.pop(0)
                    raise StopAsyncIteration

            return _Iter()

    mock_channel = AsyncMock()
    mock_channel.declare_queue.return_value = DummyQueue()
    mock_conn = AsyncMock()
    mock_conn.channel.return_value = mock_channel

    with patch("services.alerter.main.get_rabbitmq_connection", return_value=mock_conn), \
         patch("services.alerter.main.handle_alert_event", new_callable=AsyncMock) as mock_handle, \
         patch("services.alerter.main.close_redis", new_callable=AsyncMock), \
         patch("services.alerter.main.close_rabbitmq", new_callable=AsyncMock):

        await alerter_main()
        assert mock_handle.called


@pytest.mark.asyncio
async def test_telegram_notifier_edge_cases():
    notifier = TelegramNotifier()
    with patch.object(settings, "TELEGRAM_BOT_TOKEN", ""):
        assert await notifier.send("123", "msg") is False

    with patch.object(settings, "TELEGRAM_BOT_TOKEN", "token"):
        assert await notifier.send("", "msg") is False

        mock_resp_200 = httpx.Response(200, request=httpx.Request("POST", "https://api.telegram.org"))
        with patch("httpx.AsyncClient.post", return_value=mock_resp_200):
            assert await notifier.send("123", "msg") is True

        mock_resp_400 = httpx.Response(400, request=httpx.Request("POST", "https://api.telegram.org"))
        with patch("httpx.AsyncClient.post", return_value=mock_resp_400):
            assert await notifier.send("123", "msg") is False

        with patch("httpx.AsyncClient.post", side_effect=httpx.RequestError("Network down")):
            assert await notifier.send("123", "msg") is False


@pytest.mark.asyncio
async def test_discord_notifier_edge_cases():
    notifier = DiscordNotifier()
    assert await notifier.send("", "msg") is False
    assert await notifier.send("invalid-url", "msg") is False

    webhook_url = "https://discord.com/api/webhooks/123/token"
    mock_resp_204 = httpx.Response(204, request=httpx.Request("POST", webhook_url))
    with patch("httpx.AsyncClient.post", return_value=mock_resp_204):
        assert await notifier.send(webhook_url, "msg") is True

    mock_resp_429 = httpx.Response(429, request=httpx.Request("POST", webhook_url))
    with patch("httpx.AsyncClient.post", return_value=mock_resp_429):
        assert await notifier.send(webhook_url, "msg") is False

    with patch("httpx.AsyncClient.post", side_effect=httpx.RequestError("Discord down")):
        assert await notifier.send(webhook_url, "msg") is False


@pytest.mark.asyncio
async def test_email_notifier_edge_cases():
    notifier = EmailNotifier()
    with patch.object(settings, "SMTP_HOST", ""):
        assert await notifier.send("dest@example.com", "msg") is False

    with patch.object(settings, "SMTP_HOST", "smtp.example.com"), \
         patch.object(settings, "SMTP_PORT", 587), \
         patch.object(settings, "SMTP_USE_TLS", True), \
         patch.object(settings, "SMTP_USER", "user"), \
         patch.object(settings, "SMTP_PASSWORD", "pass"):

        assert await notifier.send("", "msg") is False

        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        with patch("smtplib.SMTP", return_value=mock_smtp):
            assert await notifier.send("dest@example.com", "msg", "Alert") is True
            mock_smtp.starttls.assert_called_once()
            mock_smtp.login.assert_called_once_with("user", "pass")
            mock_smtp.send_message.assert_called_once()

        with patch.object(settings, "SMTP_USE_TLS", False), \
             patch.object(settings, "SMTP_USER", ""), \
             patch.object(settings, "SMTP_PASSWORD", ""):
            mock_smtp_plain = MagicMock()
            mock_smtp_plain.__enter__.return_value = mock_smtp_plain
            with patch("smtplib.SMTP", return_value=mock_smtp_plain):
                assert await notifier.send("dest@example.com", "msg") is True
                mock_smtp_plain.starttls.assert_not_called()
                mock_smtp_plain.login.assert_not_called()

        with patch("smtplib.SMTP", side_effect=Exception("Connection refused")):
            assert await notifier.send("dest@example.com", "msg") is False


@pytest.mark.asyncio
async def test_get_notifier_and_send_notification():
    assert isinstance(get_notifier("telegram"), TelegramNotifier)
    assert isinstance(get_notifier("TELEGRAM"), TelegramNotifier)
    assert isinstance(get_notifier("discord"), DiscordNotifier)
    assert isinstance(get_notifier("email"), EmailNotifier)
    assert isinstance(get_notifier("webhook"), WebhookNotifier)
    assert get_notifier("unsupported") is None
    assert get_notifier("") is None

    assert await send_notification("unknown", "dest", "msg") is False

    with patch.object(TelegramNotifier, "send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = True
        result = await send_notification("telegram", "123", "msg", "title")
        assert result is True
        mock_send.assert_called_once_with("123", "msg", title="title")


@pytest.mark.asyncio
async def test_webhook_notifier_scenarios():
    notifier = WebhookNotifier()
    assert await notifier.send("", "msg") is False
    assert await notifier.send("ftp://example.com", "msg") is False

    mock_resp_200 = httpx.Response(200, request=httpx.Request("POST", "https://example.com"))
    with patch("httpx.AsyncClient.post", return_value=mock_resp_200):
        assert await notifier.send("https://example.com/webhook", "msg", "Alert Title") is True

    mock_resp_500 = httpx.Response(500, request=httpx.Request("POST", "https://example.com"))
    with patch("httpx.AsyncClient.post", return_value=mock_resp_500):
        assert await notifier.send("https://example.com/webhook", "msg") is False

    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Network error")):
        assert await notifier.send("https://example.com/webhook", "msg") is False


@pytest.mark.asyncio
async def test_notify_channels_multi_channel_and_isolation(db_session: AsyncSession, test_user: User):
    monitor = Monitor(
        user_id=test_user.id,
        name="Multi Channel API",
        url="https://api.multi.com",
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    cfgs = [
        AlertConfig(monitor_id=monitor.id, channel="telegram", destination="111", is_enabled=True),
        AlertConfig(
            monitor_id=monitor.id,
            channel="discord",
            destination="https://discord.com/webhook",
            is_enabled=True,
        ),
        AlertConfig(monitor_id=monitor.id, channel="email", destination="admin@example.com", is_enabled=True),
        AlertConfig(monitor_id=monitor.id, channel="unsupported_channel", destination="unknown", is_enabled=True),
        AlertConfig(monitor_id=monitor.id, channel="telegram", destination="disabled_chat", is_enabled=False),
    ]
    for c in cfgs:
        db_session.add(c)
    await db_session.commit()

    with patch("services.alerter.state_machine.AsyncSessionLocal", return_value=db_session), \
         patch("services.alerter.state_machine.send_telegram_alert", new_callable=AsyncMock) as mock_tg, \
         patch.object(DiscordNotifier, "send", new_callable=AsyncMock) as mock_discord, \
         patch.object(EmailNotifier, "send", new_callable=AsyncMock) as mock_email:

        mock_tg.return_value = True
        mock_discord.return_value = False
        mock_email.return_value = True

        await notify_channels(monitor.id, monitor.name, "Test Multi Alert")

        mock_tg.assert_called_once_with("111", "Test Multi Alert")
        mock_discord.assert_called_once()
        mock_email.assert_called_once()


@pytest.mark.asyncio
async def test_notify_channels_all_fail_triggers_fallback(db_session: AsyncSession, test_user: User):
    monitor = Monitor(
        user_id=test_user.id,
        name="Failing API",
        url="https://api.fail.com",
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    alert_cfg = AlertConfig(
        monitor_id=monitor.id,
        channel="discord",
        destination="https://discord.com/fail",
        is_enabled=True,
    )
    db_session.add(alert_cfg)
    await db_session.commit()

    with patch("services.alerter.state_machine.AsyncSessionLocal", return_value=db_session), \
         patch.object(DiscordNotifier, "send", new_callable=AsyncMock, return_value=False), \
         patch.object(settings, "TELEGRAM_DEFAULT_CHAT_ID", "default_emergency"), \
         patch("services.alerter.state_machine.send_telegram_alert", new_callable=AsyncMock) as mock_fallback:

        await notify_channels(monitor.id, monitor.name, "Emergency Alert")
        mock_fallback.assert_called_once_with("default_emergency", "Emergency Alert")
