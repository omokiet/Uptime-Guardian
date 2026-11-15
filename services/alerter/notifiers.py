import abc
import asyncio
from email.message import EmailMessage
import smtplib
from typing import Optional
import httpx
from services.common.config import settings
from services.common.transport import AntiRebindingTransport

_alerter_httpx_client: Optional[httpx.AsyncClient] = None
_client_event_loop: Optional[asyncio.AbstractEventLoop] = None


def get_alerter_httpx_client() -> httpx.AsyncClient:
    global _alerter_httpx_client, _client_event_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if (
        _alerter_httpx_client is None
        or _alerter_httpx_client.is_closed
        or _client_event_loop is not current_loop
    ):
        limits = httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=30.0,
        )
        transport = AntiRebindingTransport(
            limits=limits,
            verify=True,
        )
        _alerter_httpx_client = httpx.AsyncClient(
            transport=transport,
            verify=True,
        )
        _client_event_loop = current_loop

    return _alerter_httpx_client


async def close_alerter_httpx_client() -> None:
    global _alerter_httpx_client, _client_event_loop
    if _alerter_httpx_client is not None and not _alerter_httpx_client.is_closed:
        await _alerter_httpx_client.aclose()
        _alerter_httpx_client = None
        _client_event_loop = None


class BaseNotifier(abc.ABC):
    @abc.abstractmethod
    async def send(self, destination: str, message: str, title: str = "") -> bool:
        pass


class TelegramNotifier(BaseNotifier):
    async def send(self, destination: str, message: str, title: str = "") -> bool:
        if not settings.TELEGRAM_BOT_TOKEN or not destination:
            return False

        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": destination,
            "text": message,
            "parse_mode": "Markdown",
        }
        try:
            client = get_alerter_httpx_client()
            resp = await client.post(url, json=payload, timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False


class DiscordNotifier(BaseNotifier):
    async def send(self, destination: str, message: str, title: str = "") -> bool:
        if not destination or not destination.startswith(("http://", "https://")):
            return False

        payload = {"content": message}
        try:
            client = get_alerter_httpx_client()
            resp = await client.post(destination, json=payload, timeout=5.0)
            return 200 <= resp.status_code < 300
        except Exception:
            return False


class WebhookNotifier(BaseNotifier):
    async def send(self, destination: str, message: str, title: str = "") -> bool:
        if not destination or not destination.startswith(("http://", "https://")):
            return False

        payload = {
            "title": title or "Uptime Guardian Alert",
            "message": message,
        }
        try:
            client = get_alerter_httpx_client()
            resp = await client.post(destination, json=payload, timeout=5.0)
            return 200 <= resp.status_code < 300
        except Exception:
            return False


def _send_smtp_sync(destination: str, message: str, title: str) -> bool:
    if not settings.SMTP_HOST or not destination:
        return False

    msg = EmailMessage()
    msg["Subject"] = title or "Uptime Guardian Alert"
    msg["From"] = settings.SMTP_FROM_EMAIL or f"alerts@{settings.SMTP_HOST}"
    msg["To"] = destination
    msg.set_content(message)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5.0) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
            return True
    except Exception:
        return False


class EmailNotifier(BaseNotifier):
    async def send(self, destination: str, message: str, title: str = "") -> bool:
        return await asyncio.to_thread(_send_smtp_sync, destination, message, title)


NOTIFIER_REGISTRY: dict[str, BaseNotifier] = {
    "telegram": TelegramNotifier(),
    "discord": DiscordNotifier(),
    "email": EmailNotifier(),
    "webhook": WebhookNotifier(),
}


def get_notifier(channel: str) -> Optional[BaseNotifier]:
    return NOTIFIER_REGISTRY.get(channel.lower()) if channel else None


async def send_notification(channel: str, destination: str, message: str, title: str = "") -> bool:
    notifier = get_notifier(channel)
    if not notifier:
        return False
    return await notifier.send(destination, message, title=title)
