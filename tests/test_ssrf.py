from unittest.mock import patch
import pytest
from services.common.ssrf import SSRFValidationError, validate_target_url


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
