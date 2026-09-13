from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from services.alerter.state_machine import handle_alert_event
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

        # 1st Fail -> PENDING_DOWN, no alert
        await handle_alert_event(event_fail)
        assert redis_hash["status"] == "PENDING_DOWN"
        assert redis_hash["consecutive_fails"] == "1"
        assert mock_tg.call_count == 0

        # 2nd Fail -> PENDING_DOWN, no alert
        await handle_alert_event(event_fail)
        assert redis_hash["status"] == "PENDING_DOWN"
        assert redis_hash["consecutive_fails"] == "2"
        assert mock_tg.call_count == 0

        # 3rd Fail -> Reaches threshold (3) -> DOWN, alert triggered!
        await handle_alert_event(event_fail)
        assert redis_hash["status"] == "DOWN"
        assert redis_hash["consecutive_fails"] == "3"
        assert mock_tg.call_count == 1

        # 4th Fail -> Under cooldown -> No duplicate alert!
        await handle_alert_event(event_fail)
        assert redis_hash["status"] == "DOWN"
        assert mock_tg.call_count == 1

        # Success event -> Recovery!
        event_success = {
            "monitor_id": str(monitor.id),
            "is_success": True,
            "url": monitor.url,
        }
        await handle_alert_event(event_success)
        assert redis_hash["status"] == "UP"
        assert redis_hash["consecutive_fails"] == "0"
        # Recovery alert sent (+1 to call_count -> 2)
        assert mock_tg.call_count == 2
