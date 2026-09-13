from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.api_gateway.dependencies import get_current_user
from services.common.database import get_db
from services.common.models import User
from services.common.schemas import Token, UserCreate, UserResponse
from services.common.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    stmt = select(User).where(User.email == user_in.email)
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email đã được đăng ký",
        )

    user = User(
        email=user_in.email,
        password_hash=hash_password(user_in.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(user_in: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    stmt = select(User).where(User.email == user_in.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_in.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không chính xác",
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[User, Depends(get_current_user)]):
    return current_user
