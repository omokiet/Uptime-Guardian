import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import AlertConfig


class AlertConfigRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, alert_id: uuid.UUID, monitor_id: uuid.UUID) -> Optional[AlertConfig]:
        stmt = select(AlertConfig).where(
            AlertConfig.id == alert_id,
            AlertConfig.monitor_id == monitor_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_monitor_id(self, monitor_id: uuid.UUID) -> List[AlertConfig]:
        stmt = select(AlertConfig).where(AlertConfig.monitor_id == monitor_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def add(self, config: AlertConfig) -> None:
        self.db.add(config)

    async def delete(self, config: AlertConfig) -> None:
        await self.db.delete(config)
