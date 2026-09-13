import time
import uuid
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from services.api_gateway.dependencies import get_current_user
from services.common.database import get_db
from services.common.models import CheckResult, HourlyUptimeSummary, Monitor, User
from services.common.redis_client import get_redis_client
from services.common.schemas import (
    CheckResultResponse,
    HourlySummaryResponse,
    MonitorCreate,
    MonitorDetailResponse,
    MonitorResponse,
    MonitorUpdate,
)

router = APIRouter(prefix="/monitors", tags=["Monitors"])


@router.post("", response_model=MonitorResponse, status_code=status.HTTP_201_CREATED)
async def create_monitor(
    monitor_in: MonitorCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
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
    db.add(monitor)
    await db.commit()
    await db.refresh(monitor)

    if monitor.is_active:
        redis_client = get_redis_client()
        now_ms = int(time.time() * 1000)
        await redis_client.zadd("scheduler:monitors", {str(monitor.id): now_ms})

    return monitor


@router.get("", response_model=List[MonitorResponse])
async def list_monitors(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    is_active: Optional[bool] = None,
):
    stmt = select(Monitor).where(Monitor.user_id == current_user.id)
    if is_active is not None:
        stmt = stmt.where(Monitor.is_active == is_active)
    stmt = stmt.order_by(desc(Monitor.created_at))
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{monitor_id}", response_model=MonitorDetailResponse)
async def get_monitor(
    monitor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = select(Monitor).where(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    monitor = result.scalar_one_or_none()

    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitor không tồn tại",
        )

    checks_stmt = (
        select(CheckResult)
        .where(CheckResult.monitor_id == monitor.id)
        .order_by(desc(CheckResult.created_at))
        .limit(20)
    )
    checks_result = await db.execute(checks_stmt)
    recent_checks = checks_result.scalars().all()

    detail = MonitorDetailResponse.model_validate(monitor)
    detail.recent_checks = [CheckResultResponse.model_validate(c) for c in recent_checks]
    return detail


@router.put("/{monitor_id}", response_model=MonitorResponse)
async def update_monitor(
    monitor_id: uuid.UUID,
    monitor_in: MonitorUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = select(Monitor).where(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    monitor = result.scalar_one_or_none()

    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitor không tồn tại",
        )

    update_data = monitor_in.model_dump(exclude_unset=True)
    was_active = monitor.is_active

    for field, value in update_data.items():
        setattr(monitor, field, value)

    await db.commit()
    await db.refresh(monitor)

    redis_client = get_redis_client()
    if monitor.is_active and not was_active:
        now_ms = int(time.time() * 1000)
        await redis_client.zadd("scheduler:monitors", {str(monitor.id): now_ms})
    elif not monitor.is_active and was_active:
        await redis_client.zrem("scheduler:monitors", str(monitor.id))

    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor(
    monitor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    hard_delete: bool = Query(default=False),
):
    stmt = select(Monitor).where(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    monitor = result.scalar_one_or_none()

    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitor không tồn tại",
        )

    redis_client = get_redis_client()
    await redis_client.zrem("scheduler:monitors", str(monitor.id))
    await redis_client.delete(f"monitor:state:{monitor.id}")

    if hard_delete:
        await db.delete(monitor)
    else:
        monitor.is_active = False

    await db.commit()
    return None


@router.get("/{monitor_id}/history", response_model=List[CheckResultResponse])
async def get_monitor_history(
    monitor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    monitor_stmt = select(Monitor).where(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
    )
    monitor_res = await db.execute(monitor_stmt)
    if not monitor_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitor không tồn tại",
        )

    stmt = (
        select(CheckResult)
        .where(CheckResult.monitor_id == monitor_id)
        .order_by(desc(CheckResult.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{monitor_id}/summary", response_model=List[HourlySummaryResponse])
async def get_monitor_summary(
    monitor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    hours: int = Query(default=24, ge=1, le=720),
):
    monitor_stmt = select(Monitor).where(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
    )
    monitor_res = await db.execute(monitor_stmt)
    if not monitor_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monitor không tồn tại",
        )

    stmt = (
        select(HourlyUptimeSummary)
        .where(HourlyUptimeSummary.monitor_id == monitor_id)
        .order_by(desc(HourlyUptimeSummary.hour_timestamp))
        .limit(hours)
    )
    result = await db.execute(stmt)
    return result.scalars().all()
