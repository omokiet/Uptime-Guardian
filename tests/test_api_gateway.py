import uuid
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from services.api_gateway.main import app, lifespan
from services.common.security import create_access_token
from services.common.ssrf import SSRFValidationError


@pytest.mark.asyncio
async def test_auth_dependencies_edge_cases(async_client: AsyncClient, db_session: AsyncSession):
    resp_invalid_token = await async_client.get(
        "/api/v1/monitors",
        headers={"Authorization": "Bearer invalid.token.value"},
    )
    assert resp_invalid_token.status_code == 401
    assert "Token không hợp lệ" in resp_invalid_token.json()["detail"]

    token_no_sub = create_access_token(data={"foo": "bar"})
    resp_no_sub = await async_client.get(
        "/api/v1/monitors",
        headers={"Authorization": f"Bearer {token_no_sub}"},
    )
    assert resp_no_sub.status_code == 401
    assert "Token thiếu định danh" in resp_no_sub.json()["detail"]

    token_invalid_uuid = create_access_token(data={"sub": "not-a-valid-uuid"})
    resp_invalid_uuid = await async_client.get(
        "/api/v1/monitors",
        headers={"Authorization": f"Bearer {token_invalid_uuid}"},
    )
    assert resp_invalid_uuid.status_code == 401
    assert "không đúng định dạng" in resp_invalid_uuid.json()["detail"]

    orphan_token = create_access_token(data={"sub": str(uuid.uuid4())})
    resp_orphan = await async_client.get(
        "/api/v1/monitors",
        headers={"Authorization": f"Bearer {orphan_token}"},
    )
    assert resp_orphan.status_code == 401
    assert "Người dùng không tồn tại" in resp_orphan.json()["detail"]


@pytest.mark.asyncio
async def test_gateway_dashboard_and_health(async_client: AsyncClient):
    resp_health = await async_client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["status"] == "ok"

    resp_dash = await async_client.get("/")
    assert resp_dash.status_code == 200

    with patch("os.path.exists", return_value=False):
        resp_root = await async_client.get("/")
        assert resp_root.status_code == 200
        assert resp_root.json()["message"] == "Uptime Guardian API Gateway"


@pytest.mark.asyncio
async def test_gateway_lifespan():
    with patch("services.api_gateway.main.close_redis", new_callable=AsyncMock) as mock_redis, \
         patch("services.api_gateway.main.close_rabbitmq", new_callable=AsyncMock) as mock_rmq:
        async with lifespan(app):
            pass
        assert mock_redis.called
        assert mock_rmq.called


@pytest.mark.asyncio
async def test_ssrf_exception_handler(async_client: AsyncClient):
    @app.get("/api/v1/test-ssrf-endpoint")
    async def dummy_route():
        raise SSRFValidationError("SSRF Attack Blocked")

    resp = await async_client.get("/api/v1/test-ssrf-endpoint")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "SSRF Attack Blocked"
