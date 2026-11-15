import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.checker.checker import (
    check_ssl_days,
    close_httpx_client,
    execute_check,
    get_httpx_client,
    process_check_job,
)
from services.checker.main import main as checker_main, run_checker_worker
from services.common.config import settings
from services.common.models import CheckResult, Monitor, User


@pytest.mark.asyncio
async def test_checker_idempotency_prevents_duplicate_run(db_session: AsyncSession):
    job_id = str(uuid.uuid4())
    monitor_id = str(uuid.uuid4())
    payload = {
        "job_id": job_id,
        "monitor_id": monitor_id,
        "url": "https://example.com",
    }

    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=True)
    with patch("services.checker.checker.get_redis_client", return_value=mock_redis):
        result = await process_check_job(payload)
        assert result is True
        assert not mock_redis.set.called

    mock_redis.exists = AsyncMock(return_value=False)
    mock_redis.set = AsyncMock(return_value=None)
    with patch("services.checker.checker.get_redis_client", return_value=mock_redis):
        result = await process_check_job(payload)
        assert result is True
        mock_redis.set.assert_called_once_with(
            f"lock:check:{job_id}",
            "1",
            ex=30,
            nx=True,
        )


@pytest.mark.asyncio
async def test_checker_executes_and_saves_result(db_session: AsyncSession, test_user: User):
    monitor = Monitor(
        user_id=test_user.id,
        name="Target Server",
        url="https://example.com",
        interval_seconds=60,
        expected_status_code=200,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    job_id = str(uuid.uuid4())
    payload = {
        "job_id": job_id,
        "monitor_id": str(monitor.id),
        "url": monitor.url,
        "expected_status_code": 200,
    }

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.exists = AsyncMock(return_value=False)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()

    fake_response = httpx.Response(status_code=200, request=httpx.Request("GET", monitor.url))
    fake_addr = [(None, None, None, None, ("93.184.216.34", 80))]

    with patch("services.checker.checker.get_redis_client", return_value=mock_redis), \
         patch("services.checker.checker.AsyncSessionLocal", return_value=db_session), \
         patch("services.checker.checker.publish_message", new_callable=AsyncMock) as mock_publish, \
         patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", return_value=fake_response), \
         patch("services.checker.checker.check_ssl_days", return_value=90):

        success = await process_check_job(payload)
        assert success is True
        assert mock_publish.called

        res_stmt = select(CheckResult).where(CheckResult.job_id == uuid.UUID(job_id))
        res = await db_session.execute(res_stmt)
        record = res.scalar_one_or_none()
        assert record is not None
        assert record.is_success is True
        assert record.status_code == 200
        assert record.ssl_days_remaining == 90
        mock_redis.set.assert_any_call(f"check:processed:{job_id}", "1", ex=300)
        mock_redis.delete.assert_called_once_with(f"lock:check:{job_id}")


@pytest.mark.asyncio
async def test_checker_crash_releases_lock_and_allows_redelivery(db_session: AsyncSession, test_user: User):
    monitor = Monitor(
        user_id=test_user.id,
        name="Crash Test Server",
        url="https://crash.example.com",
        interval_seconds=60,
        expected_status_code=200,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    job_id = str(uuid.uuid4())
    payload = {
        "job_id": job_id,
        "monitor_id": str(monitor.id),
        "url": monitor.url,
        "expected_status_code": 200,
    }

    processed_keys = set()
    in_flight_locks = set()

    async def mock_exists(key):
        return key in processed_keys

    async def mock_set(key, val, ex=None, nx=False):
        if nx and key in in_flight_locks:
            return None
        if key.startswith("lock:check:"):
            in_flight_locks.add(key)
        if key.startswith("check:processed:"):
            processed_keys.add(key)
        return True

    async def mock_delete(key):
        in_flight_locks.discard(key)

    mock_redis = AsyncMock()
    mock_redis.exists.side_effect = mock_exists
    mock_redis.set.side_effect = mock_set
    mock_redis.delete.side_effect = mock_delete

    # Attempt 1: Worker crashes during execution
    with patch("services.checker.checker.get_redis_client", return_value=mock_redis), \
         patch("services.checker.checker.execute_check", side_effect=RuntimeError("Worker OOM Killed")):
        with pytest.raises(RuntimeError) as exc_info:
            await process_check_job(payload)
        assert "Worker OOM Killed" in str(exc_info.value)
        # Lock must be released in finally, and processed key must NOT be set
        assert f"lock:check:{job_id}" not in in_flight_locks
        assert f"check:processed:{job_id}" not in processed_keys

    # Attempt 2: RabbitMQ redelivers message to surviving worker -> Succeeds
    fake_response = httpx.Response(status_code=200, request=httpx.Request("GET", monitor.url))
    fake_addr = [(None, None, None, None, ("93.184.216.34", 80))]

    with patch("services.checker.checker.get_redis_client", return_value=mock_redis), \
         patch("services.checker.checker.AsyncSessionLocal", return_value=db_session), \
         patch("services.checker.checker.publish_message", new_callable=AsyncMock), \
         patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", return_value=fake_response), \
         patch("services.checker.checker.check_ssl_days", return_value=30):

        success = await process_check_job(payload)
        assert success is True
        # Now processed key must be set
        assert f"check:processed:{job_id}" in processed_keys


@pytest.mark.asyncio
async def test_check_ssl_days_scenarios():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    future_date_str = (now_utc + datetime.timedelta(days=45)).strftime("%b %d %H:%M:%S %Y GMT")
    mock_ssl_obj = MagicMock()
    mock_ssl_obj.getpeercert.return_value = {"notAfter": future_date_str}

    mock_writer = MagicMock()
    mock_writer.get_extra_info.return_value = mock_ssl_obj
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    with patch("asyncio.open_connection", new_callable=AsyncMock, return_value=(AsyncMock(), mock_writer)):
        days = await check_ssl_days("example.com")
        assert days is not None
        assert days >= 44

    past_date_str = (now_utc - datetime.timedelta(days=5)).strftime("%b %d %H:%M:%S %Y GMT")
    mock_ssl_obj.getpeercert.return_value = {"notAfter": past_date_str}
    with patch("asyncio.open_connection", new_callable=AsyncMock, return_value=(AsyncMock(), mock_writer)):
        days_expired = await check_ssl_days("expired.example.com")
        assert days_expired == 0

    conn_err = ConnectionRefusedError("Connection refused")
    with patch("asyncio.open_connection", new_callable=AsyncMock, side_effect=conn_err):
        days_err = await check_ssl_days("error.example.com")
        assert days_err is None

    mock_writer.reset_mock()
    with patch("asyncio.open_connection", new_callable=AsyncMock, return_value=(AsyncMock(), mock_writer)), \
         patch.object(mock_ssl_obj, "getpeercert", side_effect=TimeoutError("handshake timeout")):
        days_timeout = await check_ssl_days("timeout.example.com")
        assert days_timeout is None
        assert mock_writer.close.called
        assert mock_writer.wait_closed.called


@pytest.mark.asyncio
async def test_execute_check_error_scenarios():
    fake_addr = [(None, None, None, None, ("93.184.216.34", 80))]

    with patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", side_effect=httpx.TimeoutException("Read timed out")):
        is_succ, code, rtt, err, ssl = await execute_check(
            job_id="job-1",
            monitor_id="mon-1",
            url="https://timeout.example.com",
            timeout_seconds=2,
        )
        assert is_succ is False
        assert code is None
        assert "quá thời gian chờ" in err

    with patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", side_effect=httpx.ConnectError("Connection refused")):
        is_succ, code, rtt, err, ssl = await execute_check(
            job_id="job-2",
            monitor_id="mon-2",
            url="https://refused.example.com",
        )
        assert is_succ is False
        assert "Lỗi kết nối tới máy chủ" in err

    with patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", side_effect=RuntimeError("Unexpected error")):
        is_succ, code, rtt, err, ssl = await execute_check(
            job_id="job-3",
            monitor_id="mon-3",
            url="https://unexpected.example.com",
        )
        assert is_succ is False
        assert "Lỗi không xác định" in err

    fake_loopback = [(None, None, None, None, ("127.0.0.1", 80))]
    with patch("socket.getaddrinfo", return_value=fake_loopback):
        is_succ, code, rtt, err, ssl = await execute_check(
            job_id="job-4",
            monitor_id="mon-4",
            url="http://127.0.0.1:8080",
        )
        assert is_succ is False
        assert "Anti-SSRF" in err

    fake_resp_500 = httpx.Response(status_code=500, request=httpx.Request("GET", "https://example.com"))
    with patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", return_value=fake_resp_500):
        is_succ, code, rtt, err, ssl = await execute_check(
            job_id="job-5",
            monitor_id="mon-5",
            url="https://example.com",
            expected_status_code=200,
        )
        assert is_succ is False
        assert code == 500
        assert "Mã HTTP không khớp" in err


@pytest.mark.asyncio
async def test_process_check_job_invalid_payload():
    assert await process_check_job({}) is False
    assert await process_check_job({"job_id": "1"}) is False
    assert await process_check_job({"job_id": "1", "monitor_id": "2"}) is False


@pytest.mark.asyncio
async def test_redirect_ssrf_blocked():
    fake_addr_public = [(None, None, None, None, ("93.184.216.34", 80))]
    fake_addr_private = [(None, None, None, None, ("192.168.1.1", 80))]

    def mock_getaddrinfo(host, port):
        if "internal" in host:
            return fake_addr_private
        return fake_addr_public

    resp_302 = httpx.Response(
        status_code=302,
        headers={"location": "http://internal.company.lan/admin"},
        request=httpx.Request("GET", "https://example.com"),
    )

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo), \
         patch("httpx.AsyncClient.request", return_value=resp_302):
        is_succ, code, rtt, err, ssl = await execute_check(
            job_id="job-redir-1",
            monitor_id="mon-redir-1",
            url="https://example.com",
            expected_status_code=200,
        )
        assert is_succ is False
        assert code == 302
        assert "Anti-SSRF" in err


@pytest.mark.asyncio
async def test_redirect_loop_detected():
    fake_addr = [(None, None, None, None, ("93.184.216.34", 80))]

    async def mock_request(self, method, url, **kwargs):
        if "loop-a" in str(url):
            return httpx.Response(
                status_code=302,
                headers={"location": "https://example.com/loop-b"},
                request=httpx.Request("GET", str(url)),
            )
        return httpx.Response(
            status_code=302,
            headers={"location": "https://example.com/loop-a"},
            request=httpx.Request("GET", str(url)),
        )

    with patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", new=mock_request):
        is_succ, code, rtt, err, ssl = await execute_check(
            job_id="job-loop-1",
            monitor_id="mon-loop-1",
            url="https://example.com/loop-a",
            expected_status_code=200,
        )
        assert is_succ is False
        assert code == 302
        assert "Redirect loop" in err


@pytest.mark.asyncio
async def test_max_redirects_exceeded():
    fake_addr = [(None, None, None, None, ("93.184.216.34", 80))]
    step = 0

    async def mock_request(self, method, url, **kwargs):
        nonlocal step
        step += 1
        return httpx.Response(
            status_code=302,
            headers={"location": f"https://example.com/step-{step}"},
            request=httpx.Request("GET", str(url)),
        )

    with patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", new=mock_request):
        is_succ, code, rtt, err, ssl = await execute_check(
            job_id="job-max-1",
            monitor_id="mon-max-1",
            url="https://example.com/step-0",
            expected_status_code=200,
        )
        assert is_succ is False
        assert code == 302
        assert "Vượt quá số lần chuyển hướng tối đa" in err


@pytest.mark.asyncio
async def test_valid_redirect_success():
    fake_addr = [(None, None, None, None, ("93.184.216.34", 80))]

    async def mock_request(self, method, url, **kwargs):
        if "/old" in str(url):
            return httpx.Response(
                status_code=301,
                headers={"location": "/new"},
                request=httpx.Request("GET", str(url)),
            )
        return httpx.Response(
            status_code=200,
            request=httpx.Request("GET", str(url)),
        )

    with patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", new=mock_request):
        is_succ, code, rtt, err, ssl = await execute_check(
            job_id="job-succ-1",
            monitor_id="mon-succ-1",
            url="https://example.com/old",
            expected_status_code=200,
        )
        assert is_succ is True
        assert code == 200
        assert err is None


@pytest.mark.asyncio
async def test_httpx_client_lifecycle():
    client = get_httpx_client()
    assert client is not None
    assert not client.is_closed

    await close_httpx_client()
    new_client = get_httpx_client()
    assert new_client is not None
    await close_httpx_client()


@pytest.mark.asyncio
async def test_checker_worker_and_main():
    processed_requeue_flags = []

    class DummyMessage:
        def __init__(self, body: bytes):
            self.body = body

        def process(self, requeue: bool = False):
            processed_requeue_flags.append(requeue)

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
                        DummyMessage(b'{"job_id": "test"}'),
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

    with patch("services.checker.main.get_rabbitmq_connection", return_value=mock_conn), \
         patch("services.checker.main.process_check_job", new_callable=AsyncMock) as mock_process, \
         patch("services.checker.main.start_metrics_server") as mock_metrics_srv, \
         patch("services.checker.main.close_httpx_client", new_callable=AsyncMock), \
         patch("services.checker.main.close_redis", new_callable=AsyncMock), \
         patch("services.checker.main.close_rabbitmq", new_callable=AsyncMock):

        await checker_main()
        assert mock_process.called
        assert mock_metrics_srv.called
        # Valid message must use requeue=True; poison JSON message must drop with requeue=False
        assert processed_requeue_flags == [True, False]


@pytest.mark.asyncio
async def test_checker_worker_requeues_on_transient_failure():
    requeue_flags = []

    class DummyMessage:
        def __init__(self, body: bytes):
            self.body = body

        def process(self, requeue: bool = False):
            requeue_flags.append(requeue)

            class _Ctx:
                async def __aenter__(s):
                    return None

                async def __aexit__(s, exc_type, exc_val, exc_tb):
                    # Suppress exception inside test context so generator can proceed
                    return True

            return _Ctx()

    class DummyQueue:
        def iterator(self):
            class _Iter:
                async def __aenter__(s):
                    return s

                async def __aexit__(s, *args):
                    return None

                def __aiter__(s):
                    s._items = [DummyMessage(b'{"job_id": "transient-fail"}')]
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

    with patch("services.checker.main.get_rabbitmq_connection", return_value=mock_conn), \
         patch("services.checker.main.process_check_job", side_effect=RuntimeError("PostgreSQL connection lost")):
        await run_checker_worker()
        # Message must be rejected with requeue=True so RabbitMQ redelivers
        assert requeue_flags == [True]


@pytest.mark.asyncio
async def test_checker_ssl_cache_hit_skips_socket_handshake():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="45")
    fake_response = httpx.Response(
        status_code=200,
        request=httpx.Request("GET", "https://cached-ssl.example.com"),
    )
    fake_addr = [(None, None, None, None, ("93.184.216.34", 443))]

    with patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", return_value=fake_response), \
         patch("services.checker.checker.check_ssl_days", new_callable=AsyncMock) as mock_ssl_days:

        is_success, code, latency, err, ssl_days = await execute_check(
            job_id=str(uuid.uuid4()),
            monitor_id=str(uuid.uuid4()),
            url="https://cached-ssl.example.com/health",
            redis_client=mock_redis,
        )

        assert is_success is True
        assert code == 200
        assert ssl_days == 45
        mock_redis.get.assert_called_once_with("ssl:cert:cached-ssl.example.com:443")
        assert not mock_ssl_days.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "detected_days,expected_ttl",
    [
        (30, 43200),
        (5, 3600),
        (1, 600),
        (0, 600),
    ],
)
async def test_checker_ssl_cache_miss_populates_dynamic_ttl(detected_days: int, expected_ttl: int):
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    fake_response = httpx.Response(
        status_code=200,
        request=httpx.Request("GET", "https://uncached-ssl.example.com"),
    )
    fake_addr = [(None, None, None, None, ("93.184.216.34", 443))]

    with patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", return_value=fake_response), \
         patch("services.checker.checker.check_ssl_days", new_callable=AsyncMock, return_value=detected_days):

        is_success, code, latency, err, ssl_days = await execute_check(
            job_id=str(uuid.uuid4()),
            monitor_id=str(uuid.uuid4()),
            url="https://uncached-ssl.example.com",
            redis_client=mock_redis,
        )

        assert is_success is True
        assert ssl_days == detected_days
        mock_redis.set.assert_called_once_with(
            "ssl:cert:uncached-ssl.example.com:443",
            str(detected_days),
            ex=expected_ttl,
        )


@pytest.mark.asyncio
async def test_checker_ssl_cache_redis_failure_fail_open():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis connection dropped"))
    mock_redis.set = AsyncMock(side_effect=TimeoutError("Redis timeout"))

    fake_response = httpx.Response(
        status_code=200,
        request=httpx.Request("GET", "https://fault-injection.example.com"),
    )
    fake_addr = [(None, None, None, None, ("93.184.216.34", 443))]

    with patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", return_value=fake_response), \
         patch("services.checker.checker.check_ssl_days", new_callable=AsyncMock, return_value=20) as mock_ssl_days:

        is_success, code, latency, err, ssl_days = await execute_check(
            job_id=str(uuid.uuid4()),
            monitor_id=str(uuid.uuid4()),
            url="https://fault-injection.example.com",
            redis_client=mock_redis,
        )

        assert is_success is True
        assert ssl_days == 20
        assert mock_ssl_days.called


@pytest.mark.asyncio
async def test_checker_publishes_to_configured_alert_queue(db_session: AsyncSession, test_user: User):
    monitor = Monitor(
        user_id=test_user.id,
        name="Queue Config Target",
        url="https://queue.example.com",
        interval_seconds=60,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    job_id = str(uuid.uuid4())
    payload = {
        "job_id": job_id,
        "monitor_id": str(monitor.id),
        "url": monitor.url,
    }

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.exists = AsyncMock(return_value=False)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock()

    fake_response = httpx.Response(status_code=200, request=httpx.Request("GET", monitor.url))
    fake_addr = [(None, None, None, None, ("93.184.216.34", 443))]

    custom_queue = "custom.alert.events.test"
    with patch("services.checker.checker.get_redis_client", return_value=mock_redis), \
         patch("services.checker.checker.AsyncSessionLocal", return_value=db_session), \
         patch("services.checker.checker.publish_message", new_callable=AsyncMock) as mock_pub, \
         patch("socket.getaddrinfo", return_value=fake_addr), \
         patch("httpx.AsyncClient.request", return_value=fake_response), \
         patch("services.checker.checker.check_ssl_days", return_value=60), \
         patch.object(settings, "RABBITMQ_QUEUE_ALERT_EVENTS", custom_queue):

        res = await process_check_job(payload)
        assert res is True
        assert mock_pub.called
        # Verify first positional argument of publish_message is the configured settings queue
        queue_arg = mock_pub.call_args[0][0]
        assert queue_arg == custom_queue
