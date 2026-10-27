import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from services.api_gateway.main import app
from services.api_gateway.rate_limiter import (
    get_client_ip,
    rate_limit_login,
    rate_limit_register,
)


@pytest.mark.asyncio
async def test_auth_register_and_login_flow(async_client: AsyncClient):
    reg_payload = {"email": "newdev@example.com", "password": "securepassword123"}
    reg_resp = await async_client.post("/api/v1/auth/register", json=reg_payload)
    assert reg_resp.status_code == 201
    data = reg_resp.json()
    assert data["email"] == "newdev@example.com"
    assert "id" in data

    dup_resp = await async_client.post("/api/v1/auth/register", json=reg_payload)
    assert dup_resp.status_code == 400

    login_resp = await async_client.post("/api/v1/auth/login", json=reg_payload)
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert "access_token" in login_data

    token = login_data["access_token"]
    me_resp = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "newdev@example.com"


@pytest.mark.asyncio
async def test_auth_login_invalid_credentials(async_client: AsyncClient):
    resp = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_unauthorized(async_client: AsyncClient):
    resp = await async_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_login_rate_limiting(async_client: AsyncClient):
    app.dependency_overrides.pop(rate_limit_login, None)
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[11, 45])
    mock_redis.pipeline.return_value = mock_pipe
    mock_redis.expire = AsyncMock()

    with patch("services.api_gateway.rate_limiter.get_redis_client", return_value=mock_redis):
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "tester@example.com", "password": "securepassword123"},
            headers={"X-Forwarded-For": "203.0.113.1"},
        )
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert resp.headers["Retry-After"] == "45"


@pytest.mark.asyncio
async def test_auth_register_rate_limiting(async_client: AsyncClient):
    app.dependency_overrides.pop(rate_limit_register, None)
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[6, 120])
    mock_redis.pipeline.return_value = mock_pipe
    mock_redis.expire = AsyncMock()

    with patch("services.api_gateway.rate_limiter.get_redis_client", return_value=mock_redis):
        resp = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "rate_reg@example.com", "password": "securepassword123"},
            headers={"X-Real-IP": "198.51.100.22"},
        )
        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == "120"


@pytest.mark.asyncio
async def test_auth_rate_limiter_fail_open_on_redis_error(async_client: AsyncClient):
    app.dependency_overrides.pop(rate_limit_login, None)
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(side_effect=ConnectionError("Redis connection refused"))
    mock_redis.pipeline.return_value = mock_pipe

    with patch("services.api_gateway.rate_limiter.get_redis_client", return_value=mock_redis):
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpassword"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_login_rate_limiting_boundary(async_client: AsyncClient):
    app.dependency_overrides.pop(rate_limit_login, None)
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[10, 30])
    mock_redis.pipeline.return_value = mock_pipe
    mock_redis.expire = AsyncMock()

    with patch("services.api_gateway.rate_limiter.get_redis_client", return_value=mock_redis):
        resp_at_limit = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "boundary@example.com", "password": "wrongpassword"},
        )
        assert resp_at_limit.status_code == 401

    mock_pipe.execute = AsyncMock(return_value=[11, 29])
    with patch("services.api_gateway.rate_limiter.get_redis_client", return_value=mock_redis):
        resp_exceeded = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "boundary@example.com", "password": "wrongpassword"},
        )
        assert resp_exceeded.status_code == 429


@pytest.mark.asyncio
async def test_auth_rate_limiter_restores_missing_ttl(async_client: AsyncClient):
    app.dependency_overrides.pop(rate_limit_login, None)
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[3, -1])
    mock_redis.pipeline.return_value = mock_pipe
    mock_redis.expire = AsyncMock()

    with patch("services.api_gateway.rate_limiter.get_redis_client", return_value=mock_redis), \
         patch("services.api_gateway.rate_limiter.settings.TRUST_PROXY", True):
        await async_client.post(
            "/api/v1/auth/login",
            json={"email": "ttl_restore@example.com", "password": "wrongpassword"},
            headers={"X-Real-IP": "198.51.100.99"},
        )
        mock_redis.expire.assert_called_once_with("ratelimit:auth:login:198.51.100.99", 60)


def test_auth_get_client_ip_headers():
    req_forwarded = MagicMock()
    req_forwarded.headers = {"X-Forwarded-For": "103.21.244.2, 192.168.1.1"}
    req_forwarded.client.host = "10.0.0.5"

    with patch("services.api_gateway.rate_limiter.settings.TRUST_PROXY", False):
        assert get_client_ip(req_forwarded) == "10.0.0.5"

    with patch("services.api_gateway.rate_limiter.settings.TRUST_PROXY", True):
        assert get_client_ip(req_forwarded) == "103.21.244.2"

        req_real = MagicMock()
        req_real.headers = {"X-Real-IP": "198.51.100.5"}
        assert get_client_ip(req_real) == "198.51.100.5"

    req_client = MagicMock()
    req_client.headers = {}
    req_client.client.host = "127.0.0.1"
    assert get_client_ip(req_client) == "127.0.0.1"

    req_none = MagicMock()
    req_none.headers = {}
    req_none.client = None
    assert get_client_ip(req_none) == "unknown"


@pytest.mark.asyncio
async def test_register_race_condition_integrity_error(async_client: AsyncClient):
    with patch(
        "sqlalchemy.ext.asyncio.AsyncSession.commit",
        side_effect=IntegrityError("duplicate key", params=None, orig=Exception("unique constraint")),
    ):
        resp = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "race_user@example.com", "password": "password123"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Email đã được đăng ký"
