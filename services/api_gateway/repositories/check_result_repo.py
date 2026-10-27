import uuid
from typing import List
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import CheckResult


class CheckResultRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_recent_by_monitor_id(self, monitor_id: uuid.UUID, limit: int = 20) -> List[CheckResult]:
        stmt = (
            select(CheckResult)
            .where(CheckResult.monitor_id == monitor_id)
            .order_by(desc(CheckResult.created_at))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_history_by_monitor_id(
        self,
        monitor_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CheckResult]:
        stmt = (
            select(CheckResult)
            .where(CheckResult.monitor_id == monitor_id)
            .order_by(desc(CheckResult.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
