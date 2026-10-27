import uuid
from typing import List, Optional
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import Monitor


class MonitorRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id_and_user(self, monitor_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Monitor]:
        stmt = select(Monitor).where(
            Monitor.id == monitor_id,
            Monitor.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Monitor]:
        stmt = select(Monitor).where(Monitor.user_id == user_id)
        if is_active is not None:
            stmt = stmt.where(Monitor.is_active == is_active)
        stmt = stmt.order_by(desc(Monitor.created_at)).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def add(self, monitor: Monitor) -> None:
        self.db.add(monitor)

    async def delete(self, monitor: Monitor) -> None:
        await self.db.delete(monitor)
