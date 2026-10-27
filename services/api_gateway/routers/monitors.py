import uuid
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from services.api_gateway.dependencies import get_current_user
from services.api_gateway.services.monitor_service import MonitorService
from services.common.database import get_db
from services.common.models import User
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


def get_monitor_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MonitorService:
    redis_client = get_redis_client()
    return MonitorService(db=db, redis_client=redis_client)


@router.post("", response_model=MonitorResponse, status_code=status.HTTP_201_CREATED)
async def create_monitor(
    monitor_in: MonitorCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MonitorService, Depends(get_monitor_service)],
):
    return await service.create_monitor(current_user=current_user, monitor_in=monitor_in)


@router.get("", response_model=List[MonitorResponse])
async def list_monitors(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MonitorService, Depends(get_monitor_service)],
    is_active: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await service.list_monitors(
        current_user=current_user,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )


@router.get("/{monitor_id}", response_model=MonitorDetailResponse)
async def get_monitor(
    monitor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MonitorService, Depends(get_monitor_service)],
):
    return await service.get_monitor_detail(
        current_user=current_user,
        monitor_id=monitor_id,
    )


@router.put("/{monitor_id}", response_model=MonitorResponse)
async def update_monitor(
    monitor_id: uuid.UUID,
    monitor_in: MonitorUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MonitorService, Depends(get_monitor_service)],
):
    return await service.update_monitor(
        current_user=current_user,
        monitor_id=monitor_id,
        monitor_in=monitor_in,
    )


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor(
    monitor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MonitorService, Depends(get_monitor_service)],
    hard_delete: bool = Query(default=False),
):
    await service.delete_monitor(
        current_user=current_user,
        monitor_id=monitor_id,
        hard_delete=hard_delete,
    )
    return None


@router.get("/{monitor_id}/history", response_model=List[CheckResultResponse])
async def get_monitor_history(
    monitor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MonitorService, Depends(get_monitor_service)],
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return await service.get_monitor_history(
        current_user=current_user,
        monitor_id=monitor_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{monitor_id}/summary", response_model=List[HourlySummaryResponse])
async def get_monitor_summary(
    monitor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MonitorService, Depends(get_monitor_service)],
    hours: int = Query(default=24, ge=1, le=720),
):
    return await service.get_monitor_summary(
        current_user=current_user,
        monitor_id=monitor_id,
        hours=hours,
    )
