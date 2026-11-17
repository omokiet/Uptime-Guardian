import asyncio
from datetime import datetime, timezone
import json
import logging
import ssl
import time
import uuid
from typing import Any, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse
import httpx
from services.alerter.quorum_engine import record_vote_and_evaluate, resolve_quorum_on_timeout
from services.common.config import settings
from services.common.database import AsyncSessionLocal
from services.common.metrics import (
    CHECKER_CHECKS_TOTAL,
    CHECKER_CHECK_DURATION_SECONDS,
    CHECKER_SSL_EXPIRING_TOTAL,
)
from services.common.models import CheckResult
from services.common.rabbitmq import publish_message
from services.common.redis_client import get_redis_client
from services.common.ssrf import (
    SSRFValidationError,
    resolve_safe_ip,
    validate_target_url,
)
from services.common.transport import AntiRebindingTransport

logger = logging.getLogger(__name__)

_background_tasks: Set[asyncio.Task] = set()
_httpx_client: Optional[httpx.AsyncClient] = None


def get_httpx_client() -> httpx.AsyncClient:
    global _httpx_client
    if _httpx_client is None or _httpx_client.is_closed:
        limits = httpx.Limits(
            max_connections=200,
            max_keepalive_connections=50,
            keepalive_expiry=30.0,
        )
        transport = AntiRebindingTransport(
            limits=limits,
            verify=True,
        )
        _httpx_client = httpx.AsyncClient(
            transport=transport,
            verify=True,
        )
    return _httpx_client


async def close_httpx_client() -> None:
    global _httpx_client
    if _httpx_client is not None and not _httpx_client.is_closed:
        await _httpx_client.aclose()
        _httpx_client = None


async def check_ssl_days(
    hostname: str,
    port: int = 443,
    timeout: float = 5.0,
    server_ip: Optional[str] = None,
) -> Optional[int]:
    writer = None
    try:
        connect_target = server_ip or hostname
        context = ssl.create_default_context()
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(
                connect_target,
                port,
                ssl=context,
                server_hostname=hostname,
            )
            ssl_object = writer.get_extra_info("ssl_object")
            cert = ssl_object.getpeercert() if ssl_object else None

        if cert and "notAfter" in cert:
            expire_date = datetime.strptime(
                cert["notAfter"],
                "%b %d %H:%M:%S %Y %Z",
            ).replace(tzinfo=timezone.utc)
            delta = expire_date - datetime.now(timezone.utc)
            return max(0, delta.days)
    except Exception:
        return None
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
    return None


async def execute_check(
    job_id: str,
    monitor_id: str,
    url: str,
    method: str = "GET",
    timeout_seconds: int = 10,
    expected_status_code: int = 200,
    redis_client: Optional[Any] = None,
) -> Tuple[bool, Optional[int], Optional[int], Optional[str], Optional[int]]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, None, None, "Chỉ hỗ trợ giao thức http hoặc https", None
    if not parsed.hostname:
        return False, None, None, "URL không có hostname hợp lệ", None

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        safe_ip = resolve_safe_ip(parsed.hostname, port)
    except SSRFValidationError as exc:
        return False, None, None, str(exc), None

    ssl_days: Optional[int] = None
    if parsed.scheme == "https":
        r_client = redis_client or get_redis_client()
        ssl_cache_key = f"ssl:cert:{parsed.hostname}:{port}"
        try:
            cached_ssl = await r_client.get(ssl_cache_key)
            if isinstance(cached_ssl, (str, bytes, int)):
                ssl_days = int(cached_ssl)
        except Exception:
            ssl_days = None

        if ssl_days is None:
            ssl_days = await check_ssl_days(
                parsed.hostname,
                port,
                timeout=min(5.0, float(timeout_seconds)),
                server_ip=safe_ip,
            )
            if ssl_days is not None:
                # Dynamic TTL: 12h for healthy certs, 1h when near expiry (<=7d), 10m when critical (<=1d)
                if ssl_days > 7:
                    cache_ttl = 43200
                elif ssl_days > 1:
                    cache_ttl = 3600
                else:
                    cache_ttl = 600
                try:
                    await r_client.set(ssl_cache_key, str(ssl_days), ex=cache_ttl)
                except Exception:
                    pass

    start_time = time.perf_counter()
    current_url = url
    current_method = method
    visited_urls = {current_url}
    max_redirects = 5
    redirect_count = 0
    client = get_httpx_client()

    try:
        while True:
            elapsed = time.perf_counter() - start_time
            remaining_timeout = float(timeout_seconds) - elapsed
            if remaining_timeout <= 0:
                return False, None, int(elapsed * 1000), f"Kết nối quá thời gian chờ ({timeout_seconds}s)", ssl_days

            response = await client.request(
                method=current_method,
                url=current_url,
                timeout=remaining_timeout,
                follow_redirects=False,
            )

            if (
                response.status_code in (301, 302, 303, 307, 308)
                and "location" in response.headers
                and response.status_code != expected_status_code
            ):
                redirect_count += 1
                if redirect_count > max_redirects:
                    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                    return (
                        False,
                        response.status_code,
                        elapsed_ms,
                        f"Vượt quá số lần chuyển hướng tối đa ({max_redirects})",
                        ssl_days,
                    )

                raw_location = response.headers["location"]
                next_url = urljoin(current_url, raw_location)

                if next_url in visited_urls:
                    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                    return (
                        False,
                        response.status_code,
                        elapsed_ms,
                        f"Phát hiện vòng lặp chuyển hướng (Redirect loop: {next_url})",
                        ssl_days,
                    )

                try:
                    validate_target_url(next_url)
                except SSRFValidationError as exc:
                    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                    return False, response.status_code, elapsed_ms, str(exc), ssl_days

                visited_urls.add(next_url)
                current_url = next_url
                if response.status_code in (301, 302, 303):
                    current_method = "GET"
                continue

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
    if await redis_client.exists(f"check:processed:{job_id_str}"):
        return True

    in_flight_lock = f"lock:check:{job_id_str}"
    is_acquired = await redis_client.set(
        in_flight_lock,
        "1",
        ex=30,
        nx=True,
    )
    if not is_acquired:
        return True

    try:
        is_success, status_code, latency_ms, error_msg, ssl_days = await execute_check(
            job_id=job_id_str,
            monitor_id=monitor_id_str,
            url=url,
            method=method,
            timeout_seconds=timeout_seconds,
            expected_status_code=expected_status_code,
            redis_client=redis_client,
        )

        CHECKER_CHECKS_TOTAL.labels(
            method=method,
            status="success" if is_success else "failure",
        ).inc()
        if latency_ms is not None:
            CHECKER_CHECK_DURATION_SECONDS.labels(method=method).observe(latency_ms / 1000.0)
        if ssl_days is not None:
            if ssl_days <= 7:
                CHECKER_SSL_EXPIRING_TOTAL.labels(urgency="critical").inc()
            elif ssl_days <= 30:
                CHECKER_SSL_EXPIRING_TOTAL.labels(urgency="warning").inc()

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
                region_id=settings.REGION_ID,
            )
            session.add(check_result)
            await session.commit()

        user_id_str = payload.get("user_id")
        if user_id_str:
            telemetry_frame = {
                "event": "check_result",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": {
                    "monitor_id": monitor_id_str,
                    "region_id": settings.REGION_ID,
                    "status_code": status_code,
                    "response_time_ms": latency_ms,
                    "is_success": is_success,
                    "error_message": error_msg,
                    "ssl_days_remaining": ssl_days,
                },
            }
            try:
                await redis_client.publish(
                    f"telemetry:user:{user_id_str}",
                    json.dumps(telemetry_frame),
                )
            except Exception as exc:
                logger.error("Failed to publish telemetry to Redis: %s", exc)

        quorum_enabled = payload.get("quorum_enabled", False)
        if not is_success and quorum_enabled:
            lock_key = f"quorum:active:{monitor_id_str}"
            challenge_id = str(uuid.uuid4())
            acquired = await redis_client.set(
                lock_key,
                challenge_id,
                ex=settings.QUORUM_LOCK_TTL_SECONDS,
                nx=True,
            )
            if acquired:
                initiator_vote = {
                    "status": "FAIL",
                    "status_code": status_code,
                    "response_time_ms": latency_ms,
                    "error_message": error_msg,
                    "voted_at_utc": datetime.now(timezone.utc).isoformat(),
                }
                session_key = f"quorum:session:{challenge_id}"
                pipe = redis_client.pipeline()
                pipe.hset(session_key, settings.REGION_ID, json.dumps(initiator_vote))
                pipe.hset(session_key, "_initiator_job_id", job_id_str)
                pipe.expire(session_key, settings.QUORUM_SESSION_TTL_SECONDS)
                await pipe.execute()

                challenge_payload = {
                    "challenge_id": challenge_id,
                    "monitor_id": monitor_id_str,
                    "initiator_region": settings.REGION_ID,
                    "initiator_job_id": job_id_str,
                    "url": url,
                    "method": payload.get("method", "GET"),
                    "expected_status_code": payload.get("expected_status_code", 200),
                    "timeout_seconds": min(payload.get("timeout_seconds", 10), 5),
                    "quorum_threshold": payload.get("quorum_threshold", 2),
                    "quorum_regions": payload.get("quorum_regions", ["vn-han", "sg-sin", "us-iad"]),
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    await publish_message(
                        queue_name=f"{settings.RABBITMQ_QUEUE_QUORUM_PREFIX}.all",
                        payload=challenge_payload,
                        exchange_name=settings.RABBITMQ_EXCHANGE_QUORUM,
                        routing_key="challenge.all",
                        expiration="20000",
                    )
                except Exception:
                    await redis_client.delete(lock_key)
                    raise

                task = asyncio.create_task(
                    resolve_quorum_on_timeout(
                        challenge_id=challenge_id,
                        monitor_id=monitor_id_str,
                        initiator_job_id=job_id_str,
                        quorum_threshold=payload.get("quorum_threshold", 2),
                        quorum_regions=payload.get("quorum_regions", ["vn-han", "sg-sin", "us-iad"]),
                        url=url,
                    )
                )
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            else:
                active_cid = await redis_client.get(lock_key)
                if active_cid:
                    cid_str = active_cid.decode("utf-8") if isinstance(active_cid, bytes) else str(active_cid)
                    supp_vote = {
                        "status": "FAIL",
                        "status_code": status_code,
                        "response_time_ms": latency_ms,
                        "error_message": error_msg,
                        "voted_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                    await record_vote_and_evaluate(
                        challenge_id=cid_str,
                        monitor_id=monitor_id_str,
                        initiator_job_id=job_id_str,
                        region_id=settings.REGION_ID,
                        vote_data=supp_vote,
                        quorum_threshold=payload.get("quorum_threshold", 2),
                        quorum_regions=payload.get("quorum_regions", ["vn-han", "sg-sin", "us-iad"]),
                        url=url,
                        redis_client=redis_client,
                    )
        else:
            alert_event = {
                "job_id": job_id_str,
                "monitor_id": monitor_id_str,
                "url": url,
                "is_success": is_success,
                "status_code": status_code,
                "response_time_ms": latency_ms,
                "error_message": error_msg,
            }
            await publish_message(settings.RABBITMQ_QUEUE_ALERT_EVENTS, alert_event)

        await redis_client.set(f"check:processed:{job_id_str}", "1", ex=300)
    finally:
        await redis_client.delete(in_flight_lock)

    return True
