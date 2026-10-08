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
from services.checker.main import main as checker_main
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
    mock_redis.set = AsyncMock(return_value=None)

    with patch("services.checker.checker.get_redis_client", return_value=mock_redis):
        result = await process_check_job(payload)
        assert result is True
        mock_redis.set.assert_called_once_with(
            f"check:processed:{job_id}",
            "1",
            ex=300,
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
    mock_redis.set = AsyncMock(return_value=True)

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
         patch("services.checker.main.close_httpx_client", new_callable=AsyncMock), \
         patch("services.checker.main.close_redis", new_callable=AsyncMock), \
         patch("services.checker.main.close_rabbitmq", new_callable=AsyncMock):

        await checker_main()
        assert mock_process.called
