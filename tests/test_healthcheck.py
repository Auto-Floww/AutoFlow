"""Regression coverage for the Docker health probe's Host header."""

from __future__ import annotations

from urllib.error import HTTPError

import pytest

import healthcheck


def test_health_request_connects_to_loopback_with_app_host(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://autoflow.example/admin")

    request = healthcheck.build_health_request()

    assert request.full_url == "http://127.0.0.1:5000/health"
    assert request.get_header("Host") == "autoflow.example"


def test_health_request_defaults_to_localhost_without_app_url(monkeypatch):
    monkeypatch.delenv("APP_URL", raising=False)

    request = healthcheck.build_health_request()

    assert request.full_url == "http://127.0.0.1:5000/health"
    assert request.get_header("Host") == "localhost"


def test_healthcheck_propagates_http_failure(monkeypatch):
    error = HTTPError(
        healthcheck.HEALTH_URL,
        503,
        "service unavailable",
        hdrs=None,
        fp=None,
    )

    def fail_request(request, timeout):
        assert request.full_url == healthcheck.HEALTH_URL
        assert request.get_header("Host") == "autoflow.example"
        assert timeout == 3
        raise error

    monkeypatch.setattr(healthcheck, "urlopen", fail_request)

    with pytest.raises(HTTPError) as raised:
        healthcheck.check_health("https://autoflow.example")

    assert raised.value is error


def test_trusted_host_health_endpoint_accepts_probe_host_and_rejects_others(
    app, client
):
    app.config["TRUSTED_HOSTS"] = ["autoflow.example"]
    # Keep this focused on host validation instead of the production error
    # template, which builds links from the rejected request host.
    app.register_error_handler(400, lambda error: ("bad request", 400))
    request = healthcheck.build_health_request("https://autoflow.example")

    # The old Docker probe sent 127.0.0.1 as Host and failed under production
    # trusted-host validation, even though the TCP connection was healthy.
    old_probe = client.get("/health", headers={"Host": "127.0.0.1"})
    assert old_probe.status_code == 400

    accepted = client.get(
        "/health", headers={"Host": request.get_header("Host")}
    )
    assert accepted.status_code == 200
    assert accepted.json == {"service": "autoflow", "status": "ok"}

    rejected = client.get("/health", headers={"Host": "untrusted.example"})
    assert rejected.status_code == 400
