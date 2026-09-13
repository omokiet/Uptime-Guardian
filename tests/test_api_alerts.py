import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import Monitor, User


@pytest.mark.asyncio
async def test_alert_configs_api_flow(
    async_client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_user: User,
):
    monitor = Monitor(
        user_id=test_user.id,
        name="Alert Test Monitor",
        url="https://alert.example.com",
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    create_payload = {
        "channel": "telegram",
        "destination": "chat_id_987654",
        "is_enabled": True,
    }
    create_resp = await async_client.post(
        f"/api/v1/monitors/{monitor.id}/alerts",
        json=create_payload,
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    alert_data = create_resp.json()
    alert_id = alert_data["id"]
    assert alert_data["channel"] == "telegram"
    assert alert_data["destination"] == "chat_id_987654"

    list_resp = await async_client.get(
        f"/api/v1/monitors/{monitor.id}/alerts",
        headers=auth_headers,
    )
    assert list_resp.status_code == 200
    alerts_list = list_resp.json()
    assert len(alerts_list) == 1

    del_resp = await async_client.delete(
        f"/api/v1/monitors/{monitor.id}/alerts/{alert_id}",
        headers=auth_headers,
    )
    assert del_resp.status_code == 204

    list_after = await async_client.get(
        f"/api/v1/monitors/{monitor.id}/alerts",
        headers=auth_headers,
    )
    assert len(list_after.json()) == 0
