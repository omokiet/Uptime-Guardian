import uuid
from typing import List
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from services.common.models import HourlyUptimeSummary


class HourlySummaryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_monitor_id(self, monitor_id: uuid.UUID, hours: int = 24) -> List[HourlyUptimeSummary]:
        stmt = (
            select(HourlyUptimeSummary)
            .where(HourlyUptimeSummary.monitor_id == monitor_id)
            .order_by(desc(HourlyUptimeSummary.hour_timestamp))
            .limit(hours)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
