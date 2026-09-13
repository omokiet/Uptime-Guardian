import ipaddress
import socket
from urllib.parse import urlparse


class SSRFValidationError(ValueError):
    pass


def validate_target_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFValidationError("Chỉ hỗ trợ giao thức http hoặc https")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFValidationError("URL không có hostname hợp lệ")

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFValidationError(f"Không thể phân giải DNS cho hostname '{hostname}': {exc}")

    for item in addr_info:
        ip_str = item[4][0]
        ip = ipaddress.ip_address(ip_str)

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise SSRFValidationError(
                f"URL phân giải tới IP bị cấm ({ip_str}). Chặn kết nối tới dải mạng nội bộ/loopback (Anti-SSRF)"
            )

    return url
