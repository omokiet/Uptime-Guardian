import typing
import httpcore
from httpcore._backends.auto import AutoBackend
import httpx
from services.common.ssrf import SSRFValidationError, resolve_safe_ip


class AntiRebindingNetworkBackend(AutoBackend):
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: typing.Optional[float] = None,
        local_address: typing.Optional[str] = None,
        socket_options: typing.Optional[typing.Iterable[typing.Any]] = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            safe_ip = resolve_safe_ip(host, port)
        except SSRFValidationError as exc:
            raise httpcore.ConnectError(f"Anti-SSRF / DNS Rebinding blocked: {exc}") from exc

        return await super().connect_tcp(
            host=safe_ip,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class AntiRebindingTransport(httpx.AsyncHTTPTransport):
    def __init__(
        self,
        *args: typing.Any,
        network_backend: typing.Optional[httpcore.AsyncNetworkBackend] = None,
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        backend = network_backend or AntiRebindingNetworkBackend()
        self._pool._network_backend = backend
