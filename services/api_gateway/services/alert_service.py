import uuid
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from services.api_gateway.repositories.alert_config_repo import AlertConfigRepository
from services.api_gateway.repositories.monitor_repo import MonitorRepository
from services.common.models import AlertConfig, User
from services.common.schemas import AlertConfigCreate


class AlertService:
    def __init__(
        self,
        db: AsyncSession,
        alert_repo: Optional[AlertConfigRepository] = None,
        monitor_repo: Optional[MonitorRepository] = None,
    ):
        self.db = db
        self.alert_repo = alert_repo or AlertConfigRepository(db)
        self.monitor_repo = monitor_repo or MonitorRepository(db)

    async def create_alert_config(
        self,
        current_user: User,
        monitor_id: uuid.UUID,
        alert_in: AlertConfigCreate,
    ) -> AlertConfig:
        monitor = await self.monitor_repo.get_by_id_and_user(
            monitor_id=monitor_id,
            user_id=current_user.id,
        )
        if not monitor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitor không tồn tại",
            )

        config = AlertConfig(
            monitor_id=monitor_id,
            channel=alert_in.channel,
            destination=alert_in.destination,
            is_enabled=alert_in.is_enabled,
        )
        self.alert_repo.add(config)
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def list_alert_configs(
        self,
        current_user: User,
        monitor_id: uuid.UUID,
    ) -> List[AlertConfig]:
        monitor = await self.monitor_repo.get_by_id_and_user(
            monitor_id=monitor_id,
            user_id=current_user.id,
        )
        if not monitor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitor không tồn tại",
            )

        return await self.alert_repo.list_by_monitor_id(monitor_id=monitor_id)

    async def delete_alert_config(
        self,
        current_user: User,
        monitor_id: uuid.UUID,
        alert_id: uuid.UUID,
    ) -> None:
        monitor = await self.monitor_repo.get_by_id_and_user(
            monitor_id=monitor_id,
            user_id=current_user.id,
        )
        if not monitor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitor không tồn tại",
            )

        config = await self.alert_repo.get_by_id(
            alert_id=alert_id,
            monitor_id=monitor_id,
        )
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cấu hình cảnh báo không tồn tại",
            )

        await self.alert_repo.delete(config)
        await self.db.commit()
