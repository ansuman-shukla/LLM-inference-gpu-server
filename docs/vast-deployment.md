# Vast Deployment

## Current Bootstrap State

Status as of 2026-05-28:

```text
Vast SSH: ssh -i /home/ansuman/.ssh/id_ed25519_vast -p 21591 root@136.38.182.51
Vast device name: vast-gpu-inference-38274334
Tailscale IP: 100.120.175.118
Tailnet: ansuman00edu@gmail.com
GPU: NVIDIA RTX PRO 4000 Blackwell, 24 GiB
Existing vLLM: Qwen/Qwen3.6-27B-FP8 on 127.0.0.1:18000
```

Tailscale is installed and logged in on the Vast container. Because this
container does not expose `/dev/net/tun`, `tailscaled` is running in userspace
networking mode:

```text
tailscaled --tun=userspace-networking --state=/var/lib/tailscale/tailscaled.state --socket=/run/tailscale/tailscaled.sock --socks5-server=127.0.0.1:1055
```

Tailscale peer checks from Vast passed for:

```text
ansuman-1: 100.78.17.101
ansuman-2: 100.79.99.107
```

Important: this is not a production app deployment yet. The backend code is not
complete, so the Vast instance should only be treated as a network/bootstrap
target for now. A copy may exist at `/workspace/gpu-inference-backend` from the
initial bootstrap pass, but it is not the source of truth and should be re-synced
after the backend implementation is ready.

Normal Postgres/ClickHouse client connections may need either a Vast container
with `/dev/net/tun`/network admin support or explicit local proxying through the
userspace Tailscale SOCKS listener on `127.0.0.1:1055`.

## Private Service Routes

For the Postgres private network path from Vast, use
`docs/postgres-connectivity.md`.

For the ClickHouse private network path from Vast, use
`docs/clickhouse-connectivity.md`.

Cloudflare tunnel remains for public FastAPI HTTP traffic:

```text
model.ansuman.yral.com -> http://127.0.0.1:8000
```

Postgres must use Tailscale TCP, not Cloudflare HTTP proxying.


## Phase 7 runtime note

The app now expects Redis on `127.0.0.1:6379` for request admission. The
`infra/supervisord.conf` startup plan includes `redis-server --bind 127.0.0.1
--port 6379 --save "" --appendonly no` before the API process. Redis remains
local runtime state, not durable storage.


## Phase 15 Cloudflare tunnel note

As of 2026-05-29, `cloudflared` is installed on the Vast container:

```text
/opt/instance-tools/bin/cloudflared
cloudflared version 2026.5.0
```

The running `cloudflared` processes observed on Vast are portal quick tunnels
managed under `/opt/portal-aio/tunnel_manager`, not this repository's named
`gpu-inference-backend` tunnel for `model.ansuman.yral.com`. No named tunnel
credential file was found under `/etc/cloudflared`, `/root/.cloudflared`, or the
workspace during the Phase 15 check.

`infra/cloudflared/config.yml.example` is the intended named-tunnel config:

```text
model.ansuman.yral.com -> http://127.0.0.1:8000
```

It blocks `/metrics`, `/admin`, and `/debug` before the public FastAPI route and
does not route vLLM (`8001`) or Redis (`6379`). Public smoke on 2026-05-29
returned Cloudflare 1033 for `https://model.ansuman.yral.com/health`, so the
Cloudflare named tunnel/DNS side still needs credentials and activation before
Phase 15 public smoke checks can pass. Direct public `http://136.38.182.51:8001`
timed out, which is consistent with vLLM not being exposed publicly.


## Phase 16 supervisor note

`infra/vast/startup.sh` is now the intended one-command container entrypoint. It
defaults to `APP_DIR=/app`, creates `/var/log/gpu-inference`, and execs
`supervisord -c ${APP_DIR}/infra/supervisord.conf`. Override `APP_DIR` if the
repo is deployed somewhere else, such as `/workspace/gpu-inference-backend`.

`infra/supervisord.conf` starts processes in this priority order:

```text
10 redis
20 vllm
30 api
40 batch-worker
41 recovery-scanner
42 analytics-flusher
50 cloudflared
60 dcgm-exporter
```

The current Vast bootstrap instance has `supervisord` at
`/opt/sys-venv/shim/supervisord`. During the Phase 16 check, `redis-server` and
`dcgm-exporter` were not found in PATH, and the Phase 15 named Cloudflare tunnel
credentials were also absent. The final container image/startup environment must
provide Redis, cloudflared named-tunnel credentials, and DCGM exporter before the
full supervisor smoke tests can pass.


## GitHub Actions deployment path

The current repo deployment path is `.github/workflows/deploy-vast.yml`.

Use repository variables for the Vast SSH target:

```text
VAST_HOST=ssh7.vast.ai
VAST_SSH_PORT=10657
VAST_DEPLOY_USER=deploy
VAST_ROOT_USER=root
```

Use repository secrets for SSH and runtime credentials:

```text
VAST_ROOT_SSH_PRIVATE_KEY     # manual bootstrap only
VAST_SSH_PRIVATE_KEY          # normal non-root deploy
CLOUDFLARED_TOKEN
TAILSCALE_AUTH_KEY
DATABASE_URL
CLICKHOUSE_PASSWORD
SENTRY_DSN
HF_TOKEN                    # needed if the Hugging Face model requires accepted terms
```

The workflow has a manual bootstrap mode that logs in as root once, creates the
non-root deploy user, grants sudo, and prepares `/opt/gpu-inference-backend`.
Normal manual deploys log in only as `VAST_DEPLOY_USER`.

Deploys publish immutable releases under:

```text
/opt/gpu-inference-backend/releases/<github-sha>
```

and atomically point `/app` at the active release, preserving the existing
`infra/supervisord.conf` contract. The deploy script installs Redis,
supervisor, `uv`, `cloudflared`, Tailscale, `socat`, and `fuser`/`psmisc` if
they are missing, runs `uv sync`, runs Alembic migrations, restarts supervisor,
and waits for local `/health`.

For Vast containers without `/dev/net/tun`, Tailscale runs in userspace
networking mode. Since userspace mode does not give normal application
processes transparent routes to tailnet `100.x` addresses, deploy starts local
Postgres forwards:

```text
127.0.0.1:15432 -> Tailscale -> 100.78.17.101:15432
127.0.0.1:15433 -> Tailscale -> 100.79.99.107:15432
```

The production `DATABASE_URL` secret should therefore use:

```text
postgresql+asyncpg://USER:PASSWORD@/DBNAME?host=127.0.0.1:15432&host=127.0.0.1:15433
```

Cloudflare is token-file based for CI deploys:

```text
/etc/cloudflared/token
cloudflared tunnel --no-autoupdate run --token-file /etc/cloudflared/token
```

This keeps `CLOUDFLARED_TOKEN` out of the application `.env` and out of the
process command line. The named-tunnel config remains as a fallback when
`/etc/cloudflared/token` is absent.

The deploy defaults now serve the Qwen3.6 27B FP8 checkpoint on the Vast
template vLLM listener:

```text
VLLM_MANAGED=false
VLLM_BASE_URL=http://127.0.0.1:18000
VLLM_MODEL_PATH=Qwen/Qwen3.6-27B-FP8
VLLM_SERVED_MODEL_NAME=Qwen/Qwen3.6-27B-FP8
MODEL_IDS=Qwen/Qwen3.6-27B-FP8
VLLM_TENSOR_PARALLEL_SIZE=2
VLLM_MAX_MODEL_LEN=32768
VLLM_GPU_MEMORY_UTILIZATION=0.95
VLLM_MAX_NUM_SEQS=8
VLLM_MAX_NUM_BATCHED_TOKENS=16384
VLLM_ENABLE_CHUNKED_PREFILL=true
VLLM_MAX_NUM_PARTIAL_PREFILLS=2
VLLM_LONG_PREFILL_TOKEN_THRESHOLD=2048
VLLM_KV_CACHE_DTYPE=fp8
VLLM_REASONING_PARSER=qwen3
VLLM_TRUST_REMOTE_CODE=true
MAX_INPUT_TOKENS=24576
MAX_OUTPUT_TOKENS=8192
MAX_TOTAL_TOKENS=32768
```

The app token gates reserve 32768 total context while leaving 8192 tokens for output by default.

On the live Vast template, public traffic still passes through Caddy on `:8000`.
The gpu-inference allowlist there should forward `/health`, `/ready`, `/docs`,
`/openapi.json`, `/redoc`, and `/v1/*` to FastAPI on `127.0.0.1:8002`.
