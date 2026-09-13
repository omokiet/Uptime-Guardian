import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import Monitor, User
from services.scheduler.scheduler import process_due_monitors


@pytest.mark.asyncio
async def test_scheduler_process_due_monitors(db_session: AsyncSession, test_user: User):
    monitor = Monitor(
        user_id=test_user.id,
        name="Scheduled Target",
        url="https://example.org",
        interval_seconds=60,
        timeout_seconds=5,
        expected_status_code=200,
        is_active=True,
    )
    db_session.add(monitor)
    await db_session.commit()
    await db_session.refresh(monitor)

    mock_redis = AsyncMock()
    mock_redis.eval = AsyncMock(return_value=[str(monitor.id)])
    mock_pipeline = AsyncMock()
    mock_pipeline.zadd = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

    with patch("services.scheduler.scheduler.get_redis_client", return_value=mock_redis), \
         patch("services.scheduler.scheduler.AsyncSessionLocal", return_value=db_session), \
         patch("services.scheduler.scheduler.publish_message", new_callable=AsyncMock) as mock_publish:

        count = await process_due_monitors(limit=10)
        assert count == 1
        assert mock_publish.called
        assert mock_pipeline.zadd.called
