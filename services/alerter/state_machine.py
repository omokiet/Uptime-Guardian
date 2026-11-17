import asyncio
from datetime import datetime, timezone
import json
import logging
import time
import uuid
from sqlalchemy import select
from services.alerter.notifiers import get_notifier
from services.common.config import settings
from services.common.database import AsyncSessionLocal
from services.common.models import AlertConfig, Monitor
from services.common.redis_client import get_redis_client

logger = logging.getLogger(__name__)


LUA_SAFE_UNLOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


async def send_telegram_alert(chat_id: str, message: str) -> bool:
    notifier = get_notifier("telegram")
    if notifier:
        return await notifier.send(chat_id, message)
    return False


async def notify_channels(monitor_id: uuid.UUID, monitor_name: str, message: str) -> None:
    async with AsyncSessionLocal() as session:
        stmt = select(AlertConfig).where(
            AlertConfig.monitor_id == monitor_id,
            AlertConfig.is_enabled.is_(True),
        )
        result = await session.execute(stmt)
        configs = result.scalars().all()

    notified = False
    title = f"Uptime Guardian: {monitor_name}"
    for cfg in configs:
        if cfg.channel == "telegram":
            sent = await send_telegram_alert(cfg.destination, message)
            if sent:
                notified = True
        else:
            notifier = get_notifier(cfg.channel)
            if notifier:
                sent = await notifier.send(cfg.destination, message, title=title)
                if sent:
                    notified = True

    if not notified and settings.TELEGRAM_DEFAULT_CHAT_ID:
        await send_telegram_alert(settings.TELEGRAM_DEFAULT_CHAT_ID, message)


async def handle_alert_event(event: dict) -> None:
    monitor_id_str = event.get("monitor_id")
    is_success = event.get("is_success", False)
    error_msg = event.get("error_message", "Unknown error")
    url = event.get("url", "")

    if not monitor_id_str:
        return

    try:
        m_uuid = uuid.UUID(monitor_id_str)
    except ValueError:
        return
    redis_client = get_redis_client()
    lock_key = f"lock:alert:{monitor_id_str}"
    state_key = f"monitor:state:{monitor_id_str}"
    lock_token = str(uuid.uuid4())

    lock_acquired = False
    for _ in range(4):
        if await redis_client.set(lock_key, lock_token, ex=15, nx=True):
            lock_acquired = True
            break
        await asyncio.sleep(0.5)

    if not lock_acquired:
        raise TimeoutError(f"Could not acquire alert lock for monitor {monitor_id_str}")

    try:
        now_ms = int(time.time() * 1000)
        state_data = await redis_client.hgetall(state_key)

        current_status = state_data.get("status", "UNKNOWN")
        previous_status = current_status
        consecutive_fails = int(state_data.get("consecutive_fails", 0))
        cooldown_until = int(state_data.get("cooldown_until", 0))

        threshold = settings.CONSECUTIVE_THRESHOLD
        monitor_name = url
        msg_to_notify = None

        async with AsyncSessionLocal() as session:
            m_res = await session.execute(select(Monitor).where(Monitor.id == m_uuid))
            mon = m_res.scalar_one_or_none()
            if mon and mon.deleted_at is not None:
                await redis_client.delete(state_key)
                return

            if mon:
                threshold = mon.consecutive_threshold
                monitor_name = mon.name

            if is_success:
                if current_status == "DOWN":
                    msg_to_notify = (
                        f"*[RECOVERY] Dịch vụ đã hoạt động trở lại*\n"
                        f"• *Tên:* {monitor_name}\n"
                        f"• *URL:* {url}\n"
                        f"• *Thời gian:* `{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}`"
                    )

                current_status = "UP"
                consecutive_fails = 0
                cooldown_until = 0
            else:
                quorum_confirmed = bool(event.get("quorum_confirmed", False))
                if quorum_confirmed:
                    # Quorum consensus confirms outage across regions, bypass remaining threshold attempts
                    consecutive_fails = max(consecutive_fails + 1, threshold)
                else:
                    consecutive_fails += 1

                if consecutive_fails < threshold:
                    current_status = "PENDING_DOWN"
                else:
                    current_status = "DOWN"
                    if now_ms >= cooldown_until:
                        cooldown_ms = settings.COOLDOWN_MINUTES * 60 * 1000
                        cooldown_until = now_ms + cooldown_ms
                        msg_to_notify = (
                            f"*[DOWN ALERT] Dịch vụ ngừng hoạt động*\n"
                            f"• *Tên:* {monitor_name}\n"
                            f"• *URL:* {url}\n"
                            f"• *Lỗi:* {error_msg}\n"
                            f"• *Số lần fail liên tiếp:* {consecutive_fails}\n"
                            f"• *Thời gian:* `{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}`"
                        )

            await redis_client.hset(
                state_key,
                mapping={
                    "status": current_status,
                    "consecutive_fails": str(consecutive_fails),
                    "cooldown_until": str(cooldown_until),
                    "updated_at": str(now_ms),
                },
            )

            if mon:
                mon.current_status = current_status
                await session.commit()

            if current_status != previous_status and mon and getattr(mon, "user_id", None):
                status_event = {
                    "event": "status_change",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        "monitor_id": monitor_id_str,
                        "previous_status": previous_status,
                        "new_status": current_status,
                        "reason": error_msg if current_status == "DOWN" else "Service recovered",
                    },
                }
                try:
                    await redis_client.publish(
                        f"telemetry:user:{mon.user_id}",
                        json.dumps(status_event),
                    )
                except Exception as exc:
                    logger.error("Failed to publish status_change telemetry: %s", exc)

        if msg_to_notify:
            await notify_channels(m_uuid, monitor_name, msg_to_notify)

    finally:
        await redis_client.eval(LUA_SAFE_UNLOCK, 1, lock_key, lock_token)
