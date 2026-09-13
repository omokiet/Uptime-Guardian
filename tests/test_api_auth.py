import pytest
from httpx import AsyncClient


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
