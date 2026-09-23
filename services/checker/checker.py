import asyncio
import datetime
import socket
import ssl
import time
import uuid
from typing import Optional, Tuple
from urllib.parse import urlparse
import httpx
from services.common.database import AsyncSessionLocal
from services.common.metrics import (
    CHECKER_CHECKS_TOTAL,
    CHECKER_CHECK_DURATION_SECONDS,
    CHECKER_SSL_DAYS_REMAINING,
)
from services.common.models import CheckResult
from services.common.rabbitmq import publish_message
from services.common.redis_client import get_redis_client
from services.common.ssrf import SSRFValidationError, validate_target_url


async def check_ssl_days(hostname: str, port: int = 443, timeout: float = 5.0) -> Optional[int]:
    try:
        context = ssl.create_default_context()
        loop = asyncio.get_running_loop()
        
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(
                hostname,
                port,
                ssl=context,
                server_hostname=hostname,
            )
            ssl_object = writer.get_extra_info("ssl_object")
            cert = ssl_object.getpeercert() if ssl_object else None
            writer.close()
            await writer.wait_closed()

        if cert and "notAfter" in cert:
            expire_date = datetime.datetime.strptime(
                cert["notAfter"],
                "%b %d %H:%M:%S %Y %Z",
            ).replace(tzinfo=datetime.timezone.utc)
            delta = expire_date - datetime.datetime.now(datetime.timezone.utc)
            return max(0, delta.days)
    except Exception:
        return None
    return None


async def execute_check(
    job_id: str,
    monitor_id: str,
    url: str,
    method: str = "GET",
    timeout_seconds: int = 10,
    expected_status_code: int = 200,
) -> Tuple[bool, Optional[int], Optional[int], Optional[str], Optional[int]]:
    try:
        validate_target_url(url)
    except SSRFValidationError as exc:
        return False, None, None, str(exc), None

    parsed = urlparse(url)
    ssl_days: Optional[int] = None
    if parsed.scheme == "https" and parsed.hostname:
        port = parsed.port or 443
        ssl_days = await check_ssl_days(parsed.hostname, port, timeout=min(5.0, float(timeout_seconds)))

    start_time = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=float(timeout_seconds),
            verify=True,
        ) as client:
            response = await client.request(method=method, url=url)
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            status_code = response.status_code
            is_success = status_code == expected_status_code
            error_message = (
                None
                if is_success
                else f"Mã HTTP không khớp (nhận {status_code}, mong đợi {expected_status_code})"
            )
            return is_success, status_code, elapsed_ms, error_message, ssl_days
    except httpx.TimeoutException:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return False, None, elapsed_ms, f"Kết nối quá thời gian chờ ({timeout_seconds}s)", ssl_days
    except httpx.ConnectError as exc:
        return False, None, None, f"Lỗi kết nối tới máy chủ mục tiêu: {exc}", ssl_days
    except Exception as exc:
        return False, None, None, f"Lỗi không xác định khi kiểm tra: {exc}", ssl_days


async def process_check_job(payload: dict) -> bool:
    job_id_str = payload.get("job_id")
    monitor_id_str = payload.get("monitor_id")
    url = payload.get("url")
    method = payload.get("method", "GET")
    timeout_seconds = payload.get("timeout_seconds", 10)
    expected_status_code = payload.get("expected_status_code", 200)

    if not job_id_str or not monitor_id_str or not url:
        return False

    redis_client = get_redis_client()
    # Idempotency lock in Redis with 300s TTL: if redelivery happens, skip re-executing
    is_acquired = await redis_client.set(
        f"check:processed:{job_id_str}",
        "1",
        ex=300,
        nx=True,
    )
    if not is_acquired:
        return True

    is_success, status_code, latency_ms, error_msg, ssl_days = await execute_check(
        job_id=job_id_str,
        monitor_id=monitor_id_str,
        url=url,
        method=method,
        timeout_seconds=timeout_seconds,
        expected_status_code=expected_status_code,
    )

    CHECKER_CHECKS_TOTAL.labels(
        method=method,
        status="success" if is_success else "failure",
    ).inc()
    if latency_ms is not None:
        CHECKER_CHECK_DURATION_SECONDS.labels(method=method).observe(latency_ms / 1000.0)
    if ssl_days is not None:
        CHECKER_SSL_DAYS_REMAINING.labels(monitor_id=monitor_id_str).set(ssl_days)

    m_uuid = uuid.UUID(monitor_id_str)
    j_uuid = uuid.UUID(job_id_str)

    async with AsyncSessionLocal() as session:
        check_result = CheckResult(
            monitor_id=m_uuid,
            job_id=j_uuid,
            status_code=status_code,
            response_time_ms=latency_ms,
            is_success=is_success,
            error_message=error_msg,
            ssl_days_remaining=ssl_days,
        )
        session.add(check_result)
        await session.commit()

    alert_event = {
        "job_id": job_id_str,
        "monitor_id": monitor_id_str,
        "url": url,
        "is_success": is_success,
        "status_code": status_code,
        "response_time_ms": latency_ms,
        "error_message": error_msg,
    }
    await publish_message("alert.events", alert_event)
    return True
