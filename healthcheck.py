"""Probe the local web server with the host configured for the public app."""

from __future__ import annotations

import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


HEALTH_URL = "http://127.0.0.1:5000/health"


def build_health_request(app_url: str | None = None) -> Request:
    """Connect over loopback while presenting the app's trusted Host header."""

    configured_url = os.getenv("APP_URL", "") if app_url is None else app_url
    if configured_url:
        host = urlsplit(configured_url).hostname
        if not host:
            raise ValueError("APP_URL precisa conter um hostname para o health check.")
    else:
        host = "localhost"

    return Request(HEALTH_URL, headers={"Host": host})


def check_health(app_url: str | None = None) -> None:
    """Raise on connection or HTTP errors so Docker marks the probe unhealthy."""

    with urlopen(build_health_request(app_url), timeout=3) as response:
        response.read(1)


if __name__ == "__main__":
    check_health()
