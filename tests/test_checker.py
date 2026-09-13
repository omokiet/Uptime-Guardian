import uuid
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.checker.checker import process_check_job
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
    # Simulate that key is already acquired in Redis (returns None)
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
