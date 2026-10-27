import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
import pytest
from services.api_gateway.repositories.alert_config_repo import AlertConfigRepository
from services.api_gateway.repositories.check_result_repo import CheckResultRepository
from services.api_gateway.repositories.hourly_summary_repo import HourlySummaryRepository
from services.api_gateway.repositories.monitor_repo import MonitorRepository
from services.api_gateway.services.alert_service import AlertService
from services.api_gateway.services.monitor_service import MonitorService
from services.common.models import AlertConfig, Monitor, User
from services.common.schemas import AlertConfigCreate, MonitorCreate, MonitorUpdate


@pytest.mark.asyncio
async def test_monitor_repository_calls():
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_db.delete = AsyncMock()
    repo = MonitorRepository(mock_db)

    monitor = Monitor(id=uuid.uuid4(), user_id=uuid.uuid4(), name="Test", url="https://example.com")
    repo.add(monitor)
    assert mock_db.add.called

    await repo.delete(monitor)
    assert mock_db.delete.called

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = monitor
    mock_result.scalars.return_value.all.return_value = [monitor]
    mock_db.execute.return_value = mock_result

    res = await repo.get_by_id_and_user(monitor.id, monitor.user_id)
    assert res == monitor

    res_list = await repo.list_by_user(monitor.user_id, is_active=True, limit=10, offset=0)
    assert len(res_list) == 1


@pytest.mark.asyncio
async def test_check_result_repository_calls():
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    repo = CheckResultRepository(mock_db)
    monitor_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    res = await repo.get_recent_by_monitor_id(monitor_id, limit=20)
    assert res == []

    hist = await repo.get_history_by_monitor_id(monitor_id, limit=10, offset=5)
    assert hist == []


@pytest.mark.asyncio
async def test_alert_config_repository_calls():
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_db.delete = AsyncMock()
    repo = AlertConfigRepository(mock_db)

    config = AlertConfig(
        id=uuid.uuid4(),
        monitor_id=uuid.uuid4(),
        channel="email",
        destination="admin@example.com",
    )
    repo.add(config)
    assert mock_db.add.called

    await repo.delete(config)
    assert mock_db.delete.called

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = config
    mock_result.scalars.return_value.all.return_value = [config]
    mock_db.execute.return_value = mock_result

    res = await repo.get_by_id(config.id, config.monitor_id)
    assert res == config

    res_list = await repo.list_by_monitor_id(config.monitor_id)
    assert len(res_list) == 1


@pytest.mark.asyncio
async def test_hourly_summary_repository_calls():
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    repo = HourlySummaryRepository(mock_db)
    monitor_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    res = await repo.get_by_monitor_id(monitor_id, hours=12)
    assert res == []


@pytest.mark.asyncio
async def test_monitor_service_lifecycle_and_error_handling():
    fake_dns = [(None, None, None, None, ("93.184.216.34", 80))]
    with patch("socket.getaddrinfo", return_value=fake_dns):
        mock_db = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_redis = AsyncMock()
        user = User(id=uuid.uuid4(), email="user@example.com")
        service = MonitorService(db=mock_db, redis_client=mock_redis)

        create_in = MonitorCreate(
            name="API Test",
            url="https://api.example.com",
            interval_seconds=60,
            is_active=True,
        )
        created = await service.create_monitor(current_user=user, monitor_in=create_in)
        assert created.name == "API Test"
        assert mock_redis.zadd.called

        mock_redis.zadd.side_effect = Exception("Redis connection refused")
        created_error_safe = await service.create_monitor(current_user=user, monitor_in=create_in)
        assert created_error_safe.name == "API Test"
        mock_redis.zadd.side_effect = None

        inactive_in = MonitorCreate(name="Inactive", url="https://api.example.com", is_active=False)
        mock_redis.zadd.reset_mock()
        created_inactive = await service.create_monitor(current_user=user, monitor_in=inactive_in)
        assert created_inactive.is_active is False
        assert not mock_redis.zadd.called

        service.monitor_repo.get_by_id_and_user = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc_info:
            await service.get_monitor_detail(current_user=user, monitor_id=uuid.uuid4())
        assert exc_info.value.status_code == 404

        with pytest.raises(HTTPException):
            await service.update_monitor(
                current_user=user,
                monitor_id=uuid.uuid4(),
                monitor_in=MonitorUpdate(name="New"),
            )

        with pytest.raises(HTTPException):
            await service.delete_monitor(current_user=user, monitor_id=uuid.uuid4())

        with pytest.raises(HTTPException):
            await service.get_monitor_history(current_user=user, monitor_id=uuid.uuid4())

        with pytest.raises(HTTPException):
            await service.get_monitor_summary(current_user=user, monitor_id=uuid.uuid4())

        now_dt = datetime.now(timezone.utc)
        existing_monitor = Monitor(
            id=uuid.uuid4(),
            user_id=user.id,
            name="Existing",
            url="https://example.com",
            method="GET",
            interval_seconds=60,
            timeout_seconds=10,
            expected_status_code=200,
            consecutive_threshold=3,
            current_status="UP",
            is_active=True,
            created_at=now_dt,
            updated_at=now_dt,
        )
        service.monitor_repo.get_by_id_and_user = AsyncMock(return_value=existing_monitor)
        service.check_result_repo.get_recent_by_monitor_id = AsyncMock(return_value=[])

        detail = await service.get_monitor_detail(current_user=user, monitor_id=existing_monitor.id)
        assert detail.name == "Existing"

        updated = await service.update_monitor(
            current_user=user,
            monitor_id=existing_monitor.id,
            monitor_in=MonitorUpdate(is_active=False),
        )
        assert updated.is_active is False
        assert mock_redis.zrem.called

        existing_monitor.is_active = False
        mock_redis.zadd.reset_mock()
        reactivated = await service.update_monitor(
            current_user=user,
            monitor_id=existing_monitor.id,
            monitor_in=MonitorUpdate(is_active=True),
        )
        assert reactivated.is_active is True
        assert mock_redis.zadd.called

        await service.delete_monitor(current_user=user, monitor_id=existing_monitor.id, hard_delete=False)
        assert existing_monitor.is_active is False

        service.monitor_repo.delete = AsyncMock()
        await service.delete_monitor(current_user=user, monitor_id=existing_monitor.id, hard_delete=True)
        assert service.monitor_repo.delete.called


@pytest.mark.asyncio
async def test_alert_service_operations():
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    user = User(id=uuid.uuid4(), email="user@example.com")
    service = AlertService(db=mock_db)

    service.monitor_repo.get_by_id_and_user = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc_info:
        await service.create_alert_config(
            current_user=user,
            monitor_id=uuid.uuid4(),
            alert_in=AlertConfigCreate(channel="email", destination="dev@example.com"),
        )
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException):
        await service.list_alert_configs(current_user=user, monitor_id=uuid.uuid4())

    with pytest.raises(HTTPException):
        await service.delete_alert_config(current_user=user, monitor_id=uuid.uuid4(), alert_id=uuid.uuid4())

    monitor = Monitor(id=uuid.uuid4(), user_id=user.id, name="M", url="https://m.com")
    service.monitor_repo.get_by_id_and_user = AsyncMock(return_value=monitor)

    service.alert_repo.get_by_id = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc_alert_404:
        await service.delete_alert_config(current_user=user, monitor_id=monitor.id, alert_id=uuid.uuid4())
    assert exc_alert_404.value.status_code == 404

    config = AlertConfig(id=uuid.uuid4(), monitor_id=monitor.id, channel="email", destination="a@b.com")
    service.alert_repo.get_by_id = AsyncMock(return_value=config)
    service.alert_repo.delete = AsyncMock()
    await service.delete_alert_config(current_user=user, monitor_id=monitor.id, alert_id=config.id)
    assert service.alert_repo.delete.called

    service.alert_repo.list_by_monitor_id = AsyncMock(return_value=[config])
    configs = await service.list_alert_configs(current_user=user, monitor_id=monitor.id)
    assert len(configs) == 1

    fake_safe_ip = [(None, None, None, None, ("93.184.216.34", 443))]
    with patch("socket.getaddrinfo", return_value=fake_safe_ip):
        created_cfg = await service.create_alert_config(
            current_user=user,
            monitor_id=monitor.id,
            alert_in=AlertConfigCreate(channel="webhook", destination="https://webhook"),
        )
        assert created_cfg.channel == "webhook"
