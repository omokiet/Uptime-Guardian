from pathlib import Path
import socket
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
import aio_pika
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
import yaml
from services.alerter.main import main as alerter_main, run_alerter_worker
from services.checker.main import (
    main as checker_main,
    run_checker_worker,
    start_metrics_server as start_checker_metrics,
)
from services.common.database import get_db
from services.common.rabbitmq import close_rabbitmq, get_rabbitmq_connection, publish_message
from services.common.redis_client import close_redis, get_redis_client, get_redis_pool
from services.common.ssrf import SSRFValidationError, validate_target_url
from services.scheduler.main import (
    main as scheduler_main,
    start_metrics_server as start_scheduler_metrics,
)


@pytest.mark.asyncio
async def test_get_db_generator():
    mock_session = AsyncMock(spec=AsyncSession)

    class DummyContext:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("services.common.database.AsyncSessionLocal", return_value=DummyContext()):
        gen: AsyncGenerator[AsyncSession, None] = get_db()
        session = await anext(gen)
        assert session is mock_session
        with pytest.raises(StopAsyncIteration):
            await anext(gen)


@pytest.mark.asyncio
async def test_redis_client_lifecycle():
    pool = get_redis_pool()
    assert pool is not None
    client = get_redis_client()
    assert client is not None

    with patch.object(pool, "disconnect", new_callable=AsyncMock) as mock_disc:
        await close_redis()
        assert mock_disc.called

    await close_redis()


@pytest.mark.asyncio
async def test_rabbitmq_lifecycle():
    mock_conn = AsyncMock(spec=aio_pika.abc.AbstractRobustConnection)
    mock_conn.is_closed = False
    mock_channel = AsyncMock()
    mock_conn.channel.return_value.__aenter__.return_value = mock_channel

    with patch("aio_pika.connect_robust", new_callable=AsyncMock, return_value=mock_conn):
        conn = await get_rabbitmq_connection()
        assert conn is mock_conn

        await publish_message("test_queue", {"key": "value1"})
        await publish_message("test_queue", {"key": "value2"})
        assert mock_channel.declare_queue.call_count == 1
        assert mock_channel.default_exchange.publish.call_count == 2

        await close_rabbitmq()
        assert mock_conn.close.called


def test_ssrf_dns_resolution_failure():
    with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name resolution failed")):
        with pytest.raises(SSRFValidationError, match="Không thể phân giải DNS"):
            validate_target_url("https://nonexistent-domain-xyz123.com")


class MockMessageContext:
    def __init__(self, message):
        self.message = message

    async def __aenter__(self):
        return self.message

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockQueueIterator:
    def __init__(self, messages):
        self.messages = messages

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def __aiter__(self):
        for msg in self.messages:
            yield msg


@pytest.mark.asyncio
async def test_alerter_worker_execution():
    mock_msg = MagicMock()
    mock_msg.body = b'{"monitor_id": "00000000-0000-0000-0000-000000000001", "is_success": true}'
    mock_msg.process = MagicMock(return_value=MockMessageContext(mock_msg))

    mock_queue = AsyncMock()
    mock_queue.iterator = MagicMock(return_value=MockQueueIterator([mock_msg]))

    mock_channel = AsyncMock()
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    mock_conn = AsyncMock()
    mock_conn.channel = AsyncMock(return_value=mock_channel)

    with patch("services.alerter.main.get_rabbitmq_connection", new_callable=AsyncMock, return_value=mock_conn), \
         patch("services.alerter.main.handle_alert_event", new_callable=AsyncMock) as mock_handle:
        await run_alerter_worker()
        assert mock_handle.called

    with patch("services.alerter.main.run_alerter_worker", new_callable=AsyncMock), \
         patch("services.alerter.main.close_redis", new_callable=AsyncMock) as mock_redis, \
         patch("services.alerter.main.close_rabbitmq", new_callable=AsyncMock) as mock_rmq:
        await alerter_main()
        assert mock_redis.called
        assert mock_rmq.called


@pytest.mark.asyncio
async def test_checker_worker_execution():
    mock_msg = MagicMock()
    mock_msg.body = b'{"job_id": "00000000-0000-0000-0000-000000000001", "url": "https://example.com"}'
    mock_msg.process = MagicMock(return_value=MockMessageContext(mock_msg))

    mock_queue = AsyncMock()
    mock_queue.iterator = MagicMock(return_value=MockQueueIterator([mock_msg]))

    mock_channel = AsyncMock()
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    mock_conn = AsyncMock()
    mock_conn.channel = AsyncMock(return_value=mock_channel)

    with patch("services.checker.main.get_rabbitmq_connection", new_callable=AsyncMock, return_value=mock_conn), \
         patch("services.checker.main.process_check_job", new_callable=AsyncMock) as mock_process:
        await run_checker_worker()
        assert mock_process.called

    with patch("services.checker.main.run_checker_worker", new_callable=AsyncMock), \
         patch("services.checker.main.run_quorum_consumer", new_callable=AsyncMock), \
         patch("services.checker.main.close_redis", new_callable=AsyncMock) as mock_redis, \
         patch("services.checker.main.close_rabbitmq", new_callable=AsyncMock) as mock_rmq:
        await checker_main()
        assert mock_redis.called
        assert mock_rmq.called


@pytest.mark.asyncio
async def test_scheduler_main_execution():
    with patch("services.scheduler.main.run_scheduler_loop", new_callable=AsyncMock), \
         patch("services.scheduler.main.run_telemetry_maintenance_loop", new_callable=AsyncMock), \
         patch("services.scheduler.main.run_reconciliation_loop", new_callable=AsyncMock), \
         patch("services.scheduler.main.start_metrics_server") as mock_metrics_srv, \
         patch("services.scheduler.main.close_redis", new_callable=AsyncMock) as mock_redis, \
         patch("services.scheduler.main.close_rabbitmq", new_callable=AsyncMock) as mock_rmq:
        await scheduler_main()
        assert mock_metrics_srv.called
        assert mock_redis.called
        assert mock_rmq.called


def test_metrics_server_startup_and_port_conflict():
    with patch("prometheus_client.start_http_server") as mock_start:
        start_checker_metrics(8001)
        mock_start.assert_called_once_with(8001)

    with patch("prometheus_client.start_http_server", side_effect=OSError("Address already in use")):
        # Must catch OSError cleanly without raising exception
        start_checker_metrics(8001)
        start_scheduler_metrics(8002)


def test_prometheus_scrape_configuration():
    prom_path = Path("docker/prometheus/prometheus.yml")
    assert prom_path.exists(), "docker/prometheus/prometheus.yml must exist"

    with open(prom_path, "r", encoding="utf-8") as f:
        prom_config = yaml.safe_load(f)

    jobs = {job["job_name"]: job for job in prom_config.get("scrape_configs", [])}
    assert "uptime-api-gateway" in jobs
    assert jobs["uptime-api-gateway"]["static_configs"][0]["targets"] == ["api-gateway:8000"]

    assert "uptime-checker" in jobs
    assert jobs["uptime-checker"]["static_configs"][0]["targets"] == ["checker:8001"]

    assert "uptime-scheduler" in jobs
    assert jobs["uptime-scheduler"]["static_configs"][0]["targets"] == ["scheduler:8002"]


def test_docker_compose_and_caddy_proxy_configs():
    prod_path = Path("docker/docker-compose.prod.yml")
    assert prod_path.exists()
    with open(prod_path, "r", encoding="utf-8") as f:
        prod_compose = yaml.safe_load(f)

    api_env = prod_compose["services"]["api-gateway"]["environment"]
    assert "TRUST_PROXY: \"true\"" in api_env or api_env.get("TRUST_PROXY") in (True, "true")

    # Expose metrics ports on backend workers
    assert "8001" in prod_compose["services"]["checker"]["expose"]
    assert "8002" in prod_compose["services"]["scheduler"]["expose"]

    caddy_path = Path("docker/caddy/Caddyfile")
    assert caddy_path.exists()
    caddy_content = caddy_path.read_text(encoding="utf-8")
    assert "header_up X-Real-IP {remote_host}" in caddy_content
