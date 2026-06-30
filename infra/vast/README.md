# Vast Deployment

This deploy path runs directly inside the Vast Ubuntu + vLLM container. It does
not use Docker.

## GitHub Configuration

Repository variables:

```text
VAST_HOST=ssh7.vast.ai
VAST_SSH_PORT=10657
VAST_DEPLOY_USER=deploy
VAST_ROOT_USER=root
VAST_APP_ROOT=/opt/gpu-inference-backend
PUBLIC_HEALTH_URL=https://model.ansuman.yral.com
```

Optional runtime variables can also be set as repository variables:

```text
APP_ENV=production
LOG_LEVEL=INFO
APP_PORT=8002
REDIS_PORT=6380
CLICKHOUSE_URL=https://100.78.17.101:8443
CLICKHOUSE_DATABASE=yral
CLICKHOUSE_USER=gpu_inference
CLICKHOUSE_SECURE=true
CLICKHOUSE_VERIFY=false
MAX_INPUT_TOKENS=24576
MAX_OUTPUT_TOKENS=8192
MAX_TOTAL_TOKENS=32768
MODEL_IDS=Qwen/Qwen3.6-27B-FP8
VLLM_MANAGED=false
VLLM_BASE_URL=http://127.0.0.1:18000
VLLM_MODEL_PATH=Qwen/Qwen3.6-27B-FP8
VLLM_SERVED_MODEL_NAME=Qwen/Qwen3.6-27B-FP8
VLLM_TENSOR_PARALLEL_SIZE=2
VLLM_MAX_MODEL_LEN=32768
VLLM_GPU_MEMORY_UTILIZATION=0.95
VLLM_MAX_NUM_SEQS=8
VLLM_MAX_NUM_BATCHED_TOKENS=16384
VLLM_ENABLE_CHUNKED_PREFILL=true
VLLM_KV_CACHE_DTYPE=fp8
VLLM_REASONING_PARSER=qwen3
VLLM_TRUST_REMOTE_CODE=true
```

## External vLLM on the Vast template (port 18000)

The live instance uses the Vast image supervisor program `vllm` (not `infra/supervisord.conf`
`program:vllm`). That process reads `/etc/environment`:

```text
VLLM_MODEL
VLLM_ARGS
GPU_COUNT
```

FastAPI is deployed with `VLLM_MANAGED=false` and `VLLM_BASE_URL=http://127.0.0.1:18000`.
`/v1/models` lists `MODEL_IDS` from the app `.env`; chat completions forward `model` to vLLM.
Only one weights checkpoint can be loaded at a time on the GPU pair.

### Switch to Qwen3.6 27B FP8

Target model: `Qwen/Qwen3.6-27B-FP8` (~27 GiB download). On a 40 GiB root
disk, set `REMOVE_OLD_CACHE=true` if another model cache is present or resize the instance
disk before switching.

On the Vast host as root:

```bash
scp -P 10657 infra/vast/switch-template-vllm-model.sh root@ssh7.vast.ai:/tmp/
ssh -p 10657 root@ssh7.vast.ai
chmod +x /tmp/switch-template-vllm-model.sh
REMOVE_OLD_CACHE=true /tmp/switch-template-vllm-model.sh Qwen/Qwen3.6-27B-FP8
```

Dry run first:

```bash
DRY_RUN=true /tmp/switch-template-vllm-model.sh Qwen/Qwen3.6-27B-FP8
```

The switch script starts vLLM with 32k context, chunked prefill, and FP8 KV cache:

```bash
VLLM_ARGS="--download-dir /workspace/models --host 127.0.0.1 --port 18000 --max-model-len 32768 --gpu-memory-utilization 0.95 --max-num-seqs 8 --max-num-batched-tokens 16384 --enable-chunked-prefill --kv-cache-dtype fp8 --reasoning-parser qwen3 --trust-remote-code"
```

After vLLM is healthy, set the same `MODEL_IDS` / `VLLM_*` values in GitHub repository
variables so the next deploy does not revert the app `.env`.

vLLM on the template image is `0.21.0`; Qwen recommends vLLM `>=0.19.0` for Qwen3.6.
The model natively supports contexts above 128k, but if the 2x L4 instance OOMs,
lower `VLLM_MAX_NUM_SEQS`, `VLLM_MAX_NUM_BATCHED_TOKENS`, or `VLLM_MAX_MODEL_LEN`.

Repository secrets:

```text
VAST_ROOT_SSH_PRIVATE_KEY     # only used by the manual bootstrap job
VAST_SSH_PRIVATE_KEY          # used for normal deploy as VAST_DEPLOY_USER
CLOUDFLARED_TOKEN             # remotely managed Cloudflare Tunnel token
TAILSCALE_AUTH_KEY            # ephemeral/reusable auth key for Vast private networking
DATABASE_URL
CLICKHOUSE_PASSWORD
SENTRY_DSN
HF_TOKEN                    # needed if the Hugging Face model requires accepted terms
```

`CLICKHOUSE_URL`, `CLICKHOUSE_DATABASE`, and `CLICKHOUSE_USER` may be secrets
instead of variables if preferred.

## One-Time Bootstrap

Run `.github/workflows/deploy-vast.yml` manually with:

```text
bootstrap=true
deploy=true
```

The bootstrap job logs in as `VAST_ROOT_USER`, creates `VAST_DEPLOY_USER`, adds
the public key derived from `VAST_SSH_PRIVATE_KEY`, grants passwordless sudo, and
creates:

```text
/opt/gpu-inference-backend
/opt/gpu-inference-backend/releases
/var/log/gpu-inference
```

Normal manual deploys do not use root SSH.

## Deploy Flow

On each manual run, the workflow:

1. Runs `make ci`.
2. Builds a tar archive of the repository without local caches or `.env`.
3. Renders a production `.env` from GitHub secrets/variables.
4. Uploads the archive, env file, Cloudflare token file, and deploy script over
   SSH as `VAST_DEPLOY_USER`.
5. Installs required host tools if missing: Redis, supervisor, `uv`,
   `cloudflared`, Tailscale, `socat`, and `fuser`/`psmisc`.
6. Extracts the release to:

```text
/opt/gpu-inference-backend/releases/<github-sha>
```

7. Runs:

```bash
uv sync --frozen --no-dev --compile-bytecode
uv run --env-file /opt/gpu-inference-backend/releases/<github-sha>/.env alembic upgrade head
```

8. Points `/app` at the active release and restarts `supervisord`.
9. Waits for `http://127.0.0.1:8002/health`.
10. Optionally checks `PUBLIC_HEALTH_URL/health`.

Because Vast containers may not expose `/dev/net/tun`, the deploy uses
Tailscale userspace networking and local TCP forwards for Postgres:

```text
127.0.0.1:15432 -> Tailscale -> 100.78.17.101:15432
127.0.0.1:15433 -> Tailscale -> 100.79.99.107:15432
```

Use this shape for the GitHub `DATABASE_URL` secret:

```text
postgresql+asyncpg://USER:PASSWORD@/DBNAME?host=127.0.0.1:15432&host=127.0.0.1:15433
```

The Cloudflare token is stored on Vast as:

```text
/etc/cloudflared/token
```

It is not written to the app `.env`. `infra/supervisord.conf` runs cloudflared
with `--token-file` when that token file exists, with the named-tunnel config as
a fallback.

On the live Vast instance, the remotely managed Cloudflare token config still
routes `model.ansuman.yral.com` to `localhost:8000`. Caddy owns that port, so
the `:8000` Caddy block has a narrow gpu-inference route that forwards
`/health`, `/ready`, `/docs`, `/openapi.json`, `/redoc`, and `/v1/*` to FastAPI on
`127.0.0.1:8002`, while `/metrics`, `/admin`, and `/debug` return 404.

## Runtime Layout

```text
/app -> /opt/gpu-inference-backend/releases/<github-sha>
/opt/gpu-inference-backend/current -> /opt/gpu-inference-backend/releases/<github-sha>
/etc/cloudflared/token
/etc/cloudflared/config.yml
/var/log/gpu-inference/*.log
/tmp/gpu-inference-supervisor.sock
```

The supervisor starts Redis, vLLM, FastAPI, workers, analytics flusher,
cloudflared, and the optional DCGM exporter in that order.
