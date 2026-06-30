"""Integration checks for the Vast CI deployment contract."""

import subprocess
from pathlib import Path


VAST_SCRIPTS = (
    Path("infra/vast/bootstrap-deploy-user.sh"),
    Path("infra/vast/deploy-release.sh"),
    Path("infra/vast/switch-template-vllm-model.sh"),
    Path("infra/vast/write-deploy-env.sh"),
)


def test_vast_deploy_scripts_are_valid_bash() -> None:
    for script in VAST_SCRIPTS:
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_deploy_workflow_uses_non_root_deploy_user_after_bootstrap() -> None:
    workflow = Path(".github/workflows/deploy-vast.yml").read_text()

    assert "VAST_ROOT_SSH_PRIVATE_KEY" in workflow
    assert "VAST_SSH_PRIVATE_KEY" in workflow
    assert 'deploy_target="${VAST_DEPLOY_USER}@${VAST_HOST}"' in workflow
    assert "bootstrap-deploy-user.sh" in workflow
    assert "deploy-release.sh" in workflow


def test_deploy_workflow_is_manual_only() -> None:
    workflow = Path(".github/workflows/deploy-vast.yml").read_text()

    assert "workflow_dispatch:" in workflow
    assert "\n  push:\n" not in workflow
    assert "inputs.deploy" in workflow


def test_vast_deploy_path_does_not_use_docker() -> None:
    checked_text = "\n".join(
        [
            Path(".github/workflows/deploy-vast.yml").read_text(),
            *(script.read_text() for script in VAST_SCRIPTS),
        ]
    ).lower()

    assert "docker" not in checked_text


def test_cloudflared_token_is_deployed_as_token_file_not_app_env() -> None:
    workflow = Path(".github/workflows/deploy-vast.yml").read_text()
    env_writer = Path("infra/vast/write-deploy-env.sh").read_text()
    supervisor = Path("infra/supervisord.conf").read_text()

    assert "CLOUDFLARED_TOKEN" in workflow
    assert "cloudflared-token" in workflow
    assert "CLOUDFLARED_TOKEN" not in env_writer
    assert (
        "cloudflared tunnel --no-autoupdate run --token-file /etc/cloudflared/token" in supervisor
    )


def test_tailscale_authkey_is_deployed_as_token_file_not_app_env() -> None:
    workflow = Path(".github/workflows/deploy-vast.yml").read_text()
    env_writer = Path("infra/vast/write-deploy-env.sh").read_text()
    deploy_script = Path("infra/vast/deploy-release.sh").read_text()

    assert "TAILSCALE_AUTH_KEY" in workflow
    assert "tailscale-authkey" in workflow
    assert "TAILSCALE_AUTH_KEY" not in env_writer
    assert "--tun=userspace-networking" in deploy_script
    assert "socat TCP-LISTEN" in deploy_script
    assert "127.0.0.1:15433" in Path("infra/vast/README.md").read_text()


def test_deploy_env_defaults_match_l4_qwen_runtime() -> None:
    workflow = Path(".github/workflows/deploy-vast.yml").read_text()
    env_writer = Path("infra/vast/write-deploy-env.sh").read_text()

    for checked_text in (workflow, env_writer):
        assert "Qwen/Qwen3.6-27B-FP8" in checked_text
        assert "32768" in checked_text
        assert "16384" in checked_text
        assert "0.95" in checked_text
        assert "fp8" in checked_text
        assert "qwen3" in checked_text


def test_switch_template_script_syncs_app_env_with_l4_qwen_runtime() -> None:
    switch_script = Path("infra/vast/switch-template-vllm-model.sh").read_text()

    for expected in (
        'MAX_INPUT_TOKENS="24576"',
        'MAX_OUTPUT_TOKENS="8192"',
        'MAX_TOTAL_TOKENS="32768"',
        'VLLM_MAX_MODEL_LEN="32768"',
        'VLLM_GPU_MEMORY_UTILIZATION="0.95"',
        'VLLM_MAX_NUM_SEQS="8"',
        'VLLM_MAX_NUM_BATCHED_TOKENS="16384"',
        "enable-chunked-prefill",
        'VLLM_KV_CACHE_DTYPE=\\"${VLLM_KV_CACHE_DTYPE}\\"',
        'VLLM_REASONING_PARSER=\\"${VLLM_REASONING_PARSER}\\"',
        'VLLM_TRUST_REMOTE_CODE=\\"${VLLM_TRUST_REMOTE_CODE}\\"',
    ):
        assert expected in switch_script


def test_deploy_clears_stale_runtime_port_listeners_before_startup() -> None:
    deploy_script = Path("infra/vast/deploy-release.sh").read_text()

    assert "command -v fuser" in deploy_script
    assert "stop_stale_runtime_processes" in deploy_script
    assert 'stop_port_listener "${APP_HTTP_PORT}" "FastAPI"' in deploy_script
    assert 'stop_port_listener "${VLLM_HTTP_PORT}" "vLLM"' in deploy_script


def test_deploy_health_check_fails_fast_on_http_error_with_diagnostics() -> None:
    deploy_script = Path("infra/vast/deploy-release.sh").read_text()

    assert 'status_code="$(curl -sS --max-time 10' in deploy_script
    assert 'if [ "${status_code}" != "000" ]; then' in deploy_script
    assert "Health check returned HTTP ${status_code}" in deploy_script
    assert "dump_runtime_diagnostics" in deploy_script
    assert "Supervisor status:" in deploy_script
