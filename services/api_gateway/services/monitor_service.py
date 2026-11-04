from decimal import Decimal
import logging
import time
import uuid
from typing import List, Optional
from fastapi import HTTPException, status
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession
from services.api_gateway.repositories.check_result_repo import CheckResultRepository
from services.api_gateway.repositories.hourly_summary_repo import HourlySummaryRepository
from services.api_gateway.repositories.monitor_repo import MonitorRepository
from services.common.models import CheckResult, HourlyUptimeSummary, Monitor, User
from services.common.schemas import (
    CheckResultResponse,
    MonitorCreate,
    MonitorDetailResponse,
    MonitorUpdate,
)

logger = logging.getLogger(__name__)


class MonitorService:
    def __init__(
        self,
        db: AsyncSession,
        redis_client: aioredis.Redis,
        monitor_repo: Optional[MonitorRepository] = None,
        check_result_repo: Optional[CheckResultRepository] = None,
        hourly_summary_repo: Optional[HourlySummaryRepository] = None,
    ):
        self.db = db
        self.redis = redis_client
        self.monitor_repo = monitor_repo or MonitorRepository(db)
        self.check_result_repo = check_result_repo or CheckResultRepository(db)
        self.hourly_summary_repo = hourly_summary_repo or HourlySummaryRepository(db)

    async def create_monitor(self, current_user: User, monitor_in: MonitorCreate) -> Monitor:
        monitor = Monitor(
            user_id=current_user.id,
            name=monitor_in.name,
            url=monitor_in.url,
            method=monitor_in.method,
            interval_seconds=monitor_in.interval_seconds,
            timeout_seconds=monitor_in.timeout_seconds,
            expected_status_code=monitor_in.expected_status_code,
            consecutive_threshold=monitor_in.consecutive_threshold,
            is_active=monitor_in.is_active,
        )
        self.monitor_repo.add(monitor)
        await self.db.commit()
        await self.db.refresh(monitor)

        if monitor.is_active:
            try:
                now_ms = int(time.time() * 1000)
                await self.redis.zadd("scheduler:monitors", {str(monitor.id): now_ms})
            except Exception as e:
                logger.error("Failed to sync new monitor %s to Redis: %s", monitor.id, e)

        return monitor

    async def list_monitors(
        self,
        current_user: User,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Monitor]:
        return await self.monitor_repo.list_by_user(
            user_id=current_user.id,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    async def get_monitor_detail(self, current_user: User, monitor_id: uuid.UUID) -> MonitorDetailResponse:
        monitor = await self.monitor_repo.get_by_id_and_user(monitor_id=monitor_id, user_id=current_user.id)
        if not monitor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitor không tồn tại",
            )

        recent_checks = await self.check_result_repo.get_recent_by_monitor_id(monitor.id, limit=20)
        detail = MonitorDetailResponse.model_validate(monitor)
        detail.recent_checks = [CheckResultResponse.model_validate(c) for c in recent_checks]

        summaries = await self.hourly_summary_repo.get_by_monitor_id(monitor.id, hours=24)
        if summaries:
            total_checks = sum(s.total_checks for s in summaries)
            successful_checks = sum(s.success_checks for s in summaries)
            if total_checks > 0:
                detail.uptime_percentage_24h = round(Decimal((successful_checks / total_checks) * 100), 2)
            valid_rtt_items = [s for s in summaries if s.avg_response_time_ms is not None and s.total_checks > 0]
            if valid_rtt_items:
                weighted_sum = sum(s.avg_response_time_ms * s.total_checks for s in valid_rtt_items)
                total_rtt_checks = sum(s.total_checks for s in valid_rtt_items)
                if total_rtt_checks > 0:
                    detail.avg_response_time_24h = int(round(weighted_sum / total_rtt_checks))
        elif recent_checks:
            success_count = sum(1 for c in recent_checks if c.is_success)
            detail.uptime_percentage_24h = round(Decimal((success_count / len(recent_checks)) * 100), 2)
            valid_rtts = [c.response_time_ms for c in recent_checks if c.response_time_ms is not None]
            if valid_rtts:
                detail.avg_response_time_24h = int(round(sum(valid_rtts) / len(valid_rtts)))

        return detail

    async def update_monitor(
        self,
        current_user: User,
        monitor_id: uuid.UUID,
        monitor_in: MonitorUpdate,
    ) -> Monitor:
        monitor = await self.monitor_repo.get_by_id_and_user(monitor_id=monitor_id, user_id=current_user.id)
        if not monitor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitor không tồn tại",
            )

        update_data = monitor_in.model_dump(exclude_unset=True)
        was_active = monitor.is_active

        for field, value in update_data.items():
            setattr(monitor, field, value)

        await self.db.commit()
        await self.db.refresh(monitor)

        try:
            if monitor.is_active and not was_active:
                now_ms = int(time.time() * 1000)
                await self.redis.zadd("scheduler:monitors", {str(monitor.id): now_ms})
            elif not monitor.is_active and was_active:
                await self.redis.zrem("scheduler:monitors", str(monitor.id))
        except Exception as e:
            logger.error("Failed to update monitor %s status in Redis: %s", monitor.id, e)

        return monitor

    async def delete_monitor(
        self,
        current_user: User,
        monitor_id: uuid.UUID,
        hard_delete: bool = False,
    ) -> None:
        monitor = await self.monitor_repo.get_by_id_and_user(monitor_id=monitor_id, user_id=current_user.id)
        if not monitor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitor không tồn tại",
            )

        try:
            await self.redis.zrem("scheduler:monitors", str(monitor.id))
            await self.redis.delete(f"monitor:state:{monitor.id}")
        except Exception as e:
            logger.error("Failed to remove monitor %s from Redis: %s", monitor.id, e)

        if hard_delete:
            await self.monitor_repo.delete(monitor)
        else:
            monitor.is_active = False

        await self.db.commit()

    async def get_monitor_history(
        self,
        current_user: User,
        monitor_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CheckResult]:
        monitor = await self.monitor_repo.get_by_id_and_user(monitor_id=monitor_id, user_id=current_user.id)
        if not monitor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitor không tồn tại",
            )

        return await self.check_result_repo.get_history_by_monitor_id(
            monitor_id=monitor_id,
            limit=limit,
            offset=offset,
        )

    async def get_monitor_summary(
        self,
        current_user: User,
        monitor_id: uuid.UUID,
        hours: int = 24,
    ) -> List[HourlyUptimeSummary]:
        monitor = await self.monitor_repo.get_by_id_and_user(monitor_id=monitor_id, user_id=current_user.id)
        if not monitor:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitor không tồn tại",
            )

        return await self.hourly_summary_repo.get_by_monitor_id(
            monitor_id=monitor_id,
            hours=hours,
        )
