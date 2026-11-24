"""安全边界回归测试。"""

from __future__ import annotations

import logging

from app.core.logging import MaskingFormatter
from app.services import alerting


def test_webhook_hostname_resolution_rejects_private_address(monkeypatch):
    def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(alerting.socket, "getaddrinfo", resolve)
    valid, reason = alerting.validate_webhook_url("https://hooks.example.test/notify")

    assert not valid
    assert "私有" in reason or "回环" in reason


def test_webhook_hostname_resolution_failure_is_rejected(monkeypatch):
    def resolve(*args, **kwargs):
        raise OSError("dns failure")

    monkeypatch.setattr(alerting.socket, "getaddrinfo", resolve)
    valid, reason = alerting.validate_webhook_url("https://hooks.example.test/notify", allow_unresolved=False)

    assert not valid
    assert "解析" in reason


def test_webhook_private_network_override_skips_dns_check(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("private override should not resolve DNS")

    monkeypatch.setattr(alerting.socket, "getaddrinfo", fail)
    valid, reason = alerting.validate_webhook_url("https://hooks.internal.test/notify", allow_private=True)

    assert valid, reason


def test_webhook_dns_failure_is_allowed_for_configuration_validation(monkeypatch):
    def resolve(*args, **kwargs):
        raise OSError("dns failure")

    monkeypatch.setattr(alerting.socket, "getaddrinfo", resolve)
    valid, reason = alerting.validate_webhook_url("https://smtp.example.com:465", allow_unresolved=True)

    assert valid, reason


def test_regular_log_sinks_mask_credentials():
    record = logging.LogRecord("security", logging.ERROR, __file__, 1, "token=super-secret-value", (), None)
    rendered = MaskingFormatter("%(message)s").format(record)

    assert "super-secret-value" not in rendered
    assert "token=***" in rendered
