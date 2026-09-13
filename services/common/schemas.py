import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from services.common.ssrf import validate_target_url


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[uuid.UUID] = None


class MonitorBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=8)
    method: str = Field(default="GET", pattern="^(GET|POST|HEAD|PUT|DELETE)$")
    interval_seconds: int = Field(default=60, ge=10, le=86400)
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    expected_status_code: int = Field(default=200, ge=100, le=599)
    consecutive_threshold: int = Field(default=3, ge=1, le=10)
    is_active: bool = True

    @field_validator("url")
    @classmethod
    def check_url_safety(cls, value: str) -> str:
        return validate_target_url(value)


class MonitorCreate(MonitorBase):
    pass


class MonitorUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    url: Optional[str] = Field(default=None, min_length=8)
    method: Optional[str] = Field(default=None, pattern="^(GET|POST|HEAD|PUT|DELETE)$")
    interval_seconds: Optional[int] = Field(default=None, ge=10, le=86400)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=120)
    expected_status_code: Optional[int] = Field(default=None, ge=100, le=599)
    consecutive_threshold: Optional[int] = Field(default=None, ge=1, le=10)
    is_active: Optional[bool] = None

    @field_validator("url")
    @classmethod
    def check_url_safety(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return validate_target_url(value)
        return value


class MonitorResponse(MonitorBase):
    id: uuid.UUID
    user_id: uuid.UUID
    current_status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CheckResultResponse(BaseModel):
    id: int
    monitor_id: uuid.UUID
    job_id: uuid.UUID
    status_code: Optional[int]
    response_time_ms: Optional[int]
    is_success: bool
    error_message: Optional[str]
    ssl_days_remaining: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HourlySummaryResponse(BaseModel):
    id: int
    monitor_id: uuid.UUID
    hour_timestamp: datetime
    total_checks: int
    success_checks: int
    avg_response_time_ms: int
    uptime_percentage: Decimal

    model_config = ConfigDict(from_attributes=True)


class MonitorDetailResponse(MonitorResponse):
    recent_checks: List[CheckResultResponse] = []
    uptime_percentage_24h: Optional[Decimal] = None
    avg_response_time_24h: Optional[int] = None


class AlertConfigCreate(BaseModel):
    channel: str = Field(pattern="^(telegram|email|webhook)$")
    destination: str = Field(min_length=1)
    is_enabled: bool = True


class AlertConfigResponse(BaseModel):
    id: uuid.UUID
    monitor_id: uuid.UUID
    channel: str
    destination: str
    is_enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
