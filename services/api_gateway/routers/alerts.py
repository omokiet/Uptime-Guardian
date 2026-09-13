import uuid
from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.api_gateway.dependencies import get_current_user
from services.common.database import get_db
from services.common.models import AlertConfig, Monitor, User
from services.common.schemas import AlertConfigCreate, AlertConfigResponse

router = APIRouter(prefix="/monitors/{monitor_id}/alerts", tags=["Alert Configurations"])


@router.post("", response_model=AlertConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_alert_config(
    monitor_id: uuid.UUID,
    alert_in: AlertConfigCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
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

    config = AlertConfig(
        monitor_id=monitor_id,
        channel=alert_in.channel,
        destination=alert_in.destination,
        is_enabled=alert_in.is_enabled,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.get("", response_model=List[AlertConfigResponse])
async def list_alert_configs(
    monitor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
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

    stmt = select(AlertConfig).where(AlertConfig.monitor_id == monitor_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_config(
    monitor_id: uuid.UUID,
    alert_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
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

    stmt = select(AlertConfig).where(
        AlertConfig.id == alert_id,
        AlertConfig.monitor_id == monitor_id,
    )
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cấu hình cảnh báo không tồn tại",
        )

    await db.delete(config)
    await db.commit()
    return None
