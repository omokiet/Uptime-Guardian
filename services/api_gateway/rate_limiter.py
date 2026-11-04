import ipaddress
import logging
from typing import Optional
from fastapi import HTTPException, Request, status
from services.common.config import settings
from services.common.redis_client import get_redis_client

logger = logging.getLogger(__name__)

TRUSTED_PROXIES = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


def _is_trusted_proxy(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in network for network in TRUSTED_PROXIES)
    except ValueError:
        return False


def get_client_ip(request: Request) -> str:
    direct_ip = request.client.host if request.client and request.client.host else "unknown"
    if settings.TRUST_PROXY and _is_trusted_proxy(direct_ip):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            candidate = forwarded.split(",")[0].strip()
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                pass
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            candidate = real_ip.strip()
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                pass
    return direct_ip


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
