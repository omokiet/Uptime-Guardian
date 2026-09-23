import asyncio
import time
import uuid
import httpx
from sqlalchemy import select
from services.common.config import settings
from services.common.database import AsyncSessionLocal
from services.common.models import AlertConfig, Monitor
from services.common.redis_client import get_redis_client


async def send_telegram_alert(chat_id: str, message: str) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception:
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
    for cfg in configs:
        if cfg.channel == "telegram":
            await send_telegram_alert(cfg.destination, message)
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

    m_uuid = uuid.UUID(monitor_id_str)
    redis_client = get_redis_client()
    lock_key = f"lock:alert:{monitor_id_str}"
    state_key = f"monitor:state:{monitor_id_str}"

    # Distributed lock via SETNX to avoid race conditions during state transitions
    lock_acquired = await redis_client.set(lock_key, "1", ex=10, nx=True)
    if not lock_acquired:
        await asyncio.sleep(0.5)
        lock_acquired = await redis_client.set(lock_key, "1", ex=10, nx=True)
        if not lock_acquired:
            return

    try:
        now_ms = int(time.time() * 1000)
        state_data = await redis_client.hgetall(state_key)

        current_status = state_data.get("status", "UNKNOWN")
        consecutive_fails = int(state_data.get("consecutive_fails", 0))
        cooldown_until = int(state_data.get("cooldown_until", 0))

        threshold = settings.CONSECUTIVE_THRESHOLD
        monitor_name = url
        async with AsyncSessionLocal() as session:
            m_res = await session.execute(select(Monitor).where(Monitor.id == m_uuid))
            mon = m_res.scalar_one_or_none()
            if mon:
                threshold = mon.consecutive_threshold
                monitor_name = mon.name

        if is_success:
            if current_status == "DOWN":
                msg = (
                    f"✅ *[RECOVERY] Dịch vụ đã hoạt động trở lại*\n"
                    f"• *Tên:* {monitor_name}\n"
                    f"• *URL:* {url}\n"
                    f"• *Thời gian:* `{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}`"
                )
                await notify_channels(m_uuid, monitor_name, msg)

            current_status = "UP"
            consecutive_fails = 0
            cooldown_until = 0

            await redis_client.hset(
                state_key,
                mapping={
                    "status": current_status,
                    "consecutive_fails": str(consecutive_fails),
                    "cooldown_until": str(cooldown_until),
                    "updated_at": str(now_ms),
                },
            )

            async with AsyncSessionLocal() as session:
                m_res = await session.execute(select(Monitor).where(Monitor.id == m_uuid))
                mon = m_res.scalar_one_or_none()
                if mon:
                    mon.current_status = current_status
                    await session.commit()
        else:
            consecutive_fails += 1
            if consecutive_fails < threshold:
                current_status = "PENDING_DOWN"
            else:
                current_status = "DOWN"
                if now_ms >= cooldown_until:
                    cooldown_ms = settings.COOLDOWN_MINUTES * 60 * 1000
                    cooldown_until = now_ms + cooldown_ms
                    msg = (
                        f"🚨 *[DOWN ALERT] Dịch vụ ngừng hoạt động*\n"
                        f"• *Tên:* {monitor_name}\n"
                        f"• *URL:* {url}\n"
                        f"• *Lỗi:* {error_msg}\n"
                        f"• *Số lần fail liên tiếp:* {consecutive_fails}\n"
                        f"• *Thời gian:* `{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}`"
                    )
                    await notify_channels(m_uuid, monitor_name, msg)

            await redis_client.hset(
                state_key,
                mapping={
                    "status": current_status,
                    "consecutive_fails": str(consecutive_fails),
                    "cooldown_until": str(cooldown_until),
                    "updated_at": str(now_ms),
                },
            )

            async with AsyncSessionLocal() as session:
                m_res = await session.execute(select(Monitor).where(Monitor.id == m_uuid))
                mon = m_res.scalar_one_or_none()
                if mon:
                    mon.current_status = current_status
                    await session.commit()

    finally:
        await redis_client.delete(lock_key)
