import logging
from typing import Optional
from fastapi import HTTPException, Request, status
from services.common.config import settings
from services.common.redis_client import get_redis_client

logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    if settings.TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
    return request.client.host if request.client else "unknown"


class AuthRateLimiter:
    def __init__(self, scope: str, times: Optional[int] = None, seconds: Optional[int] = None):
        self.scope = scope
        self._times = times
        self._seconds = seconds

    @property
    def times(self) -> int:
        if self._times is not None:
            return self._times
        if self.scope == "login":
            return settings.AUTH_LOGIN_RATE_LIMIT
        return settings.AUTH_REGISTER_RATE_LIMIT

    @property
    def seconds(self) -> int:
        if self._seconds is not None:
            return self._seconds
        if self.scope == "login":
            return settings.AUTH_LOGIN_WINDOW_SECONDS
        return settings.AUTH_REGISTER_WINDOW_SECONDS

    async def __call__(self, request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return

        client_ip = get_client_ip(request)
        key = f"ratelimit:auth:{self.scope}:{client_ip}"

        try:
            redis = get_redis_client()
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            results = await pipe.execute()
            count, ttl = results[0], results[1]

            if count == 1 or ttl == -1:
                await redis.expire(key, self.seconds)
                ttl = self.seconds

            if count > self.times:
                retry_after = ttl if ttl > 0 else self.seconds
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Quá nhiều yêu cầu. Vui lòng thử lại sau {retry_after} giây.",
                    headers={"Retry-After": str(retry_after)},
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Rate limiter failure: %s", exc)
            return


rate_limit_login = AuthRateLimiter(scope="login")
rate_limit_register = AuthRateLimiter(scope="register")
