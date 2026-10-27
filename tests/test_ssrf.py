import ipaddress
import socket
from unittest.mock import AsyncMock, patch
import httpcore
import httpx
import pytest
from services.checker.checker import execute_check
from services.common.ssrf import (
    SSRFValidationError,
    is_ip_allowed,
    resolve_safe_ip,
    validate_target_url,
)
from services.common.transport import (
    AntiRebindingNetworkBackend,
    AntiRebindingTransport,
)


def test_ssrf_rejects_invalid_schemes():
    with pytest.raises(SSRFValidationError, match="Chỉ hỗ trợ giao thức http hoặc https"):
        validate_target_url("ftp://example.com/file")

    with pytest.raises(SSRFValidationError, match="Chỉ hỗ trợ giao thức http hoặc https"):
        validate_target_url("javascript:alert(1)")


def test_ssrf_rejects_empty_hostname():
    with pytest.raises(SSRFValidationError, match="URL không có hostname hợp lệ"):
        validate_target_url("http://")


@pytest.mark.parametrize(
    "ip_str",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.5",
        "172.16.0.10",
        "169.254.169.254",
        "::1",
    ],
)
def test_ssrf_blocks_private_and_loopback_ips(ip_str: str):
    fake_addr_info = [(None, None, None, None, (ip_str, 80))]
    with patch("socket.getaddrinfo", return_value=fake_addr_info):
        with pytest.raises(SSRFValidationError, match="Anti-SSRF"):
            validate_target_url(f"http://internal-host-{ip_str}")


def test_ssrf_allows_public_ips():
    fake_addr_info = [(None, None, None, None, ("8.8.8.8", 80))]
    with patch("socket.getaddrinfo", return_value=fake_addr_info):
        result = validate_target_url("https://dns.google.com")
        assert result == "https://dns.google.com"


@pytest.mark.parametrize(
    ("ip_str", "expected"),
    [
        ("127.0.0.1", False),
        ("::1", False),
        ("10.1.2.3", False),
        ("172.16.5.5", False),
        ("192.168.0.1", False),
        ("169.254.1.1", False),
        ("224.0.0.1", False),
        ("0.0.0.0", False),
        ("100.64.0.1", False),
        ("100.127.255.254", False),
        ("8.8.8.8", True),
        ("1.1.1.1", True),
        ("2606:4700:4700::1111", True),
    ],
)
def test_is_ip_allowed(ip_str: str, expected: bool):
    ip = ipaddress.ip_address(ip_str)
    assert is_ip_allowed(ip) is expected


def test_resolve_safe_ip_literal():
    assert resolve_safe_ip("8.8.8.8") == "8.8.8.8"
    assert resolve_safe_ip("2606:4700:4700::1111") == "2606:4700:4700::1111"

    with pytest.raises(SSRFValidationError, match="IP bị cấm"):
        resolve_safe_ip("127.0.0.1")


def test_resolve_safe_ip_mixed_records():
    fake_addr_info = [
        (None, None, None, None, ("8.8.8.8", 80)),
        (None, None, None, None, ("127.0.0.1", 80)),
    ]
    with patch("socket.getaddrinfo", return_value=fake_addr_info):
        with pytest.raises(SSRFValidationError, match="Chặn DNS Rebinding / Anti-SSRF"):
            resolve_safe_ip("attacker-mixed.com", 80)


def test_resolve_safe_ip_dns_failure():
    with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")):
        with pytest.raises(SSRFValidationError, match="Không thể phân giải DNS"):
            resolve_safe_ip("nonexistent-domain.xyz", 80)


@pytest.mark.asyncio
async def test_anti_rebinding_backend_blocks_internal_ip():
    backend = AntiRebindingNetworkBackend()
    fake_addr_info = [(None, None, None, None, ("127.0.0.1", 80))]

    with patch("socket.getaddrinfo", return_value=fake_addr_info):
        with pytest.raises(httpcore.ConnectError, match="Anti-SSRF / DNS Rebinding blocked"):
            await backend.connect_tcp("rebind.evil.com", 80)


@pytest.mark.asyncio
async def test_anti_rebinding_backend_pins_validated_ip():
    backend = AntiRebindingNetworkBackend()
    fake_addr_info = [(None, None, None, None, ("93.184.216.34", 80))]
    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)

    patch_connect = patch(
        "httpcore._backends.auto.AutoBackend.connect_tcp",
        new_callable=AsyncMock,
        return_value=mock_stream,
    )
    with patch("socket.getaddrinfo", return_value=fake_addr_info), patch_connect as mock_super_connect:
        stream = await backend.connect_tcp("example.com", 80)
        assert stream == mock_stream
        mock_super_connect.assert_called_once_with(
            host="93.184.216.34",
            port=80,
            timeout=None,
            local_address=None,
            socket_options=None,
        )


@pytest.mark.asyncio
async def test_anti_rebinding_transport_integration():
    fake_safe_addr = [(None, None, None, None, ("93.184.216.34", 80))]
    fake_rebind_addr = [(None, None, None, None, ("127.0.0.1", 80))]

    with patch("socket.getaddrinfo", return_value=fake_safe_addr):
        validate_target_url("http://rebind-test.com")

    transport = AntiRebindingTransport()
    with patch("socket.getaddrinfo", return_value=fake_rebind_addr):
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get("http://rebind-test.com")


@pytest.mark.asyncio
async def test_execute_check_ssl_ssrf_blocked():
    fake_addr_private = [(None, None, None, None, ("10.0.0.1", 443))]
    with patch("socket.getaddrinfo", return_value=fake_addr_private), \
         patch("services.checker.checker.check_ssl_days") as mock_ssl:
        is_succ, code, rtt, err, ssl_days = await execute_check(
            job_id="job-ssl-ssrf",
            monitor_id="mon-ssl-ssrf",
            url="https://internal-bank.local",
        )
        assert is_succ is False
        assert ssl_days is None
        mock_ssl.assert_not_called()
