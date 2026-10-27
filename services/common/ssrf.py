import ipaddress
import socket
from typing import Union
from urllib.parse import urlparse


class SSRFValidationError(ValueError):
    pass


def is_ip_allowed(ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
    return ip.is_global and not ip.is_multicast


def resolve_safe_ip(hostname: str, port: int = 0) -> str:
    try:
        ip = ipaddress.ip_address(hostname)
        if not is_ip_allowed(ip):
            raise SSRFValidationError(
                f"IP bị cấm ({hostname}). Chặn kết nối tới dải mạng nội bộ/loopback (Anti-SSRF)"
            )
        return str(ip)
    except ValueError:
        pass

    try:
        addr_info = socket.getaddrinfo(hostname, port)
    except socket.gaierror as exc:
        raise SSRFValidationError(f"Không thể phân giải DNS cho hostname '{hostname}': {exc}")

    if not addr_info:
        raise SSRFValidationError(f"Không tìm thấy bản ghi DNS cho hostname '{hostname}'")

    for item in addr_info:
        ip_str = item[4][0]
        ip = ipaddress.ip_address(ip_str)
        if not is_ip_allowed(ip):
            raise SSRFValidationError(
                f"DNS hostname '{hostname}' phân giải tới IP bị cấm ({ip_str}). Chặn DNS Rebinding / Anti-SSRF"
            )

    return addr_info[0][4][0]


def validate_target_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFValidationError("Chỉ hỗ trợ giao thức http hoặc https")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFValidationError("URL không có hostname hợp lệ")

    resolve_safe_ip(hostname, 0)
    return url
