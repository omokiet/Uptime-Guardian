from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_crud_monitor_lifecycle(async_client: AsyncClient, auth_headers: dict):
    fake_addr_info = [(None, None, None, None, ("93.184.216.34", 80))]
    mock_redis = AsyncMock()

    with patch("socket.getaddrinfo", return_value=fake_addr_info), \
         patch("services.api_gateway.routers.monitors.get_redis_client", return_value=mock_redis):

        create_payload = {
            "name": "Example Web Service",
            "url": "https://example.com",
            "interval_seconds": 30,
            "timeout_seconds": 5,
            "expected_status_code": 200,
            "consecutive_threshold": 3,
            "is_active": True,
        }
        create_resp = await async_client.post(
            "/api/v1/monitors",
            json=create_payload,
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        monitor_id = created["id"]
        assert created["name"] == "Example Web Service"
        assert created["interval_seconds"] == 30
        assert mock_redis.zadd.called

        list_resp = await async_client.get("/api/v1/monitors", headers=auth_headers)
        assert list_resp.status_code == 200
        monitors_list = list_resp.json()
        assert len(monitors_list) == 1

        get_resp = await async_client.get(f"/api/v1/monitors/{monitor_id}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == monitor_id

        update_resp = await async_client.put(
            f"/api/v1/monitors/{monitor_id}",
            json={"interval_seconds": 60, "is_active": False},
            headers=auth_headers,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["interval_seconds"] == 60
        assert update_resp.json()["is_active"] is False
        assert mock_redis.zrem.called

        del_resp = await async_client.delete(
            f"/api/v1/monitors/{monitor_id}?hard_delete=false",
            headers=auth_headers,
        )
        assert del_resp.status_code == 204

        active_list_resp = await async_client.get(
            "/api/v1/monitors?is_active=true",
            headers=auth_headers,
        )
        assert len(active_list_resp.json()) == 0

        hist_resp = await async_client.get(
            f"/api/v1/monitors/{monitor_id}/history",
            headers=auth_headers,
        )
        assert hist_resp.status_code == 200
        assert isinstance(hist_resp.json(), list)

        summary_resp = await async_client.get(
            f"/api/v1/monitors/{monitor_id}/summary",
            headers=auth_headers,
        )
        assert summary_resp.status_code == 200
        assert isinstance(summary_resp.json(), list)


@pytest.mark.asyncio
async def test_create_monitor_ssrf_blocked(async_client: AsyncClient, auth_headers: dict):
    fake_addr_info = [(None, None, None, None, ("127.0.0.1", 80))]

    with patch("socket.getaddrinfo", return_value=fake_addr_info):
        payload = {
            "name": "Internal Service",
            "url": "http://127.0.0.1:8080/admin",
            "interval_seconds": 30,
        }
        resp = await async_client.post("/api/v1/monitors", json=payload, headers=auth_headers)
        assert resp.status_code in (422, 400)
