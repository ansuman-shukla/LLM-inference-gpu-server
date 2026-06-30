"""Integration checks for the single-container supervisor contract."""

from configparser import RawConfigParser
from pathlib import Path


def _supervisor_config() -> RawConfigParser:
    parser = RawConfigParser()
    parser.read("infra/supervisord.conf")
    return parser


def test_supervisor_has_required_processes_in_startup_order() -> None:
    config = _supervisor_config()
    expected_priorities = {
        "program:redis": 10,
        "program:vllm": 20,
        "program:api": 30,
        "program:batch-worker": 40,
        "program:recovery-scanner": 41,
        "program:analytics-flusher": 42,
        "program:cloudflared": 50,
        "program:dcgm-exporter": 60,
    }

    for section, priority in expected_priorities.items():
        assert config.has_section(section)
        assert config.getint(section, "priority") == priority


def test_supervisor_uses_restart_policy_logs_and_group_shutdown() -> None:
    config = _supervisor_config()

    for section in config.sections():
        if not section.startswith("program:"):
            continue
        assert config.get(section, "autostart") == "true"
        assert config.has_option(section, "stdout_logfile")
        assert config.has_option(section, "stderr_logfile")
        assert config.get(section, "stopsignal") == "TERM"
        assert config.get(section, "stopasgroup") == "true"
        assert config.get(section, "killasgroup") == "true"

    assert config.get("program:dcgm-exporter", "autorestart") == "false"
    for section in set(config.sections()) - {
        "unix_http_server",
        "supervisord",
        "rpcinterface:supervisor",
        "supervisorctl",
        "program:dcgm-exporter",
    }:
        if section.startswith("program:"):
            assert config.get(section, "autorestart") == "true"


def test_supervisor_keeps_internal_services_on_localhost() -> None:
    config = _supervisor_config()

    redis_command = config.get("program:redis", "command")
    assert "--bind 127.0.0.1" in redis_command
    assert '--port "${REDIS_PORT:-6379}"' in redis_command
    assert "python -m backend.scripts.run_vllm" in config.get("program:vllm", "command")
    api_command = config.get("program:api", "command")
    assert '--host "${APP_HOST:-127.0.0.1}"' in api_command
    assert '--port "${APP_PORT:-8000}"' in api_command
    cloudflared_command = config.get("program:cloudflared", "command")
    assert '"http://${APP_HOST:-127.0.0.1}:${APP_PORT:-8000}/health"' in cloudflared_command
    assert "cloudflared tunnel --no-autoupdate run --token-file /etc/cloudflared/token" in (
        cloudflared_command
    )
    assert "cloudflared tunnel --config /etc/cloudflared/config.yml run gpu-inference-backend" in (
        cloudflared_command
    )


def test_vast_startup_execs_supervisord() -> None:
    startup = Path("infra/vast/startup.sh").read_text()

    assert "mkdir -p" in startup
    assert "exec supervisord -c" in startup
