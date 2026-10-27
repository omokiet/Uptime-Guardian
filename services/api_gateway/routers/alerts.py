import uuid
from typing import Annotated, List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from services.api_gateway.dependencies import get_current_user
from services.api_gateway.services.alert_service import AlertService
from services.common.database import get_db
from services.common.models import User
from services.common.schemas import AlertConfigCreate, AlertConfigResponse

router = APIRouter(prefix="/monitors/{monitor_id}/alerts", tags=["Alert Configurations"])


def get_alert_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AlertService:
    return AlertService(db=db)


@router.post("", response_model=AlertConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_alert_config(
    monitor_id: uuid.UUID,
    alert_in: AlertConfigCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AlertService, Depends(get_alert_service)],
):
    return await service.create_alert_config(
        current_user=current_user,
        monitor_id=monitor_id,
        alert_in=alert_in,
    )


@router.get("", response_model=List[AlertConfigResponse])
async def list_alert_configs(
    monitor_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AlertService, Depends(get_alert_service)],
):
    return await service.list_alert_configs(
        current_user=current_user,
        monitor_id=monitor_id,
    )


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_config(
    monitor_id: uuid.UUID,
    alert_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AlertService, Depends(get_alert_service)],
):
    await service.delete_alert_config(
        current_user=current_user,
        monitor_id=monitor_id,
        alert_id=alert_id,
    )
    return None
