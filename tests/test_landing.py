"""Integration checks for the public landing page and application entry points."""

import base64
import hashlib
import re


def test_public_root_serves_landing_and_real_auth_links(client):
    with client.get("/") as response:
        assert response.status_code == 200
        assert response.mimetype == "text/html"
        assert b'href="/login"' in response.data
        assert b'href="/register"' in response.data
        assert b"IA que potencializa suas vendas" in response.data


def test_landing_assets_are_served_by_flask(client):
    with client.get("/style.css") as stylesheet:
        assert stylesheet.status_code == 200
        assert stylesheet.mimetype == "text/css"
    with client.get("/script.js") as script:
        assert script.status_code == 200
        assert "javascript" in script.mimetype
    with client.get("/assets/autoflow-mark-transparent.png") as logo:
        assert logo.status_code == 200
        assert logo.mimetype == "image/png"
    with client.get("/js/phone-scroll.js") as module:
        assert module.status_code == 200
        assert "javascript" in module.mimetype


def test_landing_import_map_is_allowed_by_the_strict_csp(client):
    with client.get("/") as response:
        html = response.get_data(as_text=True)
        import_map = re.search(
            r'<script type="importmap">([\s\S]*?)</script>', html
        )

        assert import_map is not None
        assert "https://cdn.jsdelivr.net/npm/three@0.169.0/" in import_map.group(1)
        assert "unpkg.com" not in import_map.group(1)

        digest = base64.b64encode(
            hashlib.sha256(import_map.group(1).encode("utf-8")).digest()
        ).decode("ascii")
        csp = response.headers["Content-Security-Policy"]

        script_policy = csp.split("script-src", 1)[1].split(";", 1)[0]
        assert "'unsafe-inline'" not in script_policy
        assert f"'sha256-{digest}'" in csp


def test_legacy_entry_points_redirect_to_flask_routes(client):
    assert client.get("/index.html").location == "/"
    assert client.get("/login.html").location == "/login"
    assert client.get("/dashboard.html").location == "/dashboard"


def test_authenticated_root_opens_dashboard(client, login_as, tenant_user):
    login_as(tenant_user)

    response = client.get("/")

    assert response.status_code == 302
    assert response.location == "/dashboard"
