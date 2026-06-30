"""Integration checks for the Cloudflare Tunnel ingress contract."""

from pathlib import Path


def _config() -> str:
    return Path("infra/cloudflared/config.yml.example").read_text()


def test_cloudflare_tunnel_routes_public_hostname_to_fastapi_only() -> None:
    config = _config()

    assert "hostname: model.ansuman.yral.com" in config
    assert "service: http://127.0.0.1:8002" in config
    assert "8001" not in config
    assert "6379" not in config


def test_cloudflare_tunnel_blocks_private_paths_before_public_route() -> None:
    config = _config()
    public_service = config.index("service: http://127.0.0.1:8002")

    for path in ("/metrics", "/metrics/*", "/admin", "/admin/*", "/debug", "/debug/*"):
        path_rule = config.index(f"path: {path}")
        blocked_service = config.index("service: http_status:404", path_rule)
        assert path_rule < blocked_service < public_service
