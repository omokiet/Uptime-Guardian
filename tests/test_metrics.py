from httpx import AsyncClient
import pytest
from prometheus_client import REGISTRY
from services.common.metrics import (
    API_HTTP_REQUESTS_TOTAL,
    API_HTTP_REQUEST_DURATION_SECONDS,
    CHECKER_CHECKS_TOTAL,
    CHECKER_CHECK_DURATION_SECONDS,
    SCHEDULER_DISPATCHED_JOBS_TOTAL,
)


@pytest.mark.asyncio
async def test_metrics_endpoint_exposition(async_client: AsyncClient) -> None:
    response = await async_client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    content = response.text
    assert "# HELP" in content
    assert "# TYPE" in content


@pytest.mark.asyncio
async def test_api_gateway_metrics_collection(async_client: AsyncClient) -> None:
    initial_before = REGISTRY.get_sample_value(
        "api_http_requests_total",
        labels={"method": "GET", "endpoint": "/health", "status_code": "200"},
    ) or 0.0

    res = await async_client.get("/health")
    assert res.status_code == 200

    after = REGISTRY.get_sample_value(
        "api_http_requests_total",
        labels={"method": "GET", "endpoint": "/health", "status_code": "200"},
    )
    assert after is not None
    assert after == initial_before + 1.0


def test_checker_metrics_increment() -> None:
    initial_val = REGISTRY.get_sample_value(
        "checker_checks_total",
        labels={"method": "GET", "status": "success"},
    ) or 0.0

    CHECKER_CHECKS_TOTAL.labels(method="GET", status="success").inc()
    CHECKER_CHECK_DURATION_SECONDS.labels(method="GET").observe(0.125)

    updated_val = REGISTRY.get_sample_value(
        "checker_checks_total",
        labels={"method": "GET", "status": "success"},
    )
    assert updated_val == initial_val + 1.0


def test_scheduler_metrics_increment() -> None:
    initial_val = REGISTRY.get_sample_value("scheduler_dispatched_jobs_total") or 0.0
    SCHEDULER_DISPATCHED_JOBS_TOTAL.inc()
    updated_val = REGISTRY.get_sample_value("scheduler_dispatched_jobs_total")
    assert updated_val == initial_val + 1.0
