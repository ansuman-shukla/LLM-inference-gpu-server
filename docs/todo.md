
# TODO: Production-Style GPU Inference Backend

## Non-negotiable implementation rules

This code will run inside VAST AI container 

```
Vast vLLM container
  ├── Redis
  ├── vLLM on 127.0.0.1:8001
  ├── FastAPI Gateway on 127.0.0.1:8000
  ├── analytics flusher
  ├── batch worker
  ├── cloudflared
  └── exporters / metrics helpers

Vast container image:
  vastai/vllm:<pinned-stable-tag>

Inside container:
  Redis:
    127.0.0.1:6379

  vLLM:
    127.0.0.1:8001

  FastAPI:
    127.0.0.1:8000

  cloudflared:
    nsfw-model.ansuman.yral.com → http://127.0.0.1:8000

External:
  Postgres:
    postgress.ansuman.yral.com

  ClickHouse:
    clickhouse.ansuman.yral.com

  Sentry:
    existing self-hosted Sentry

  Prometheus/Grafana:
    ansuman-1 / ansuman-2 / ansuman-3


supervisord
  ├── redis-server
  ├── vllm serve ...
  ├── uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
  ├── uv run python -m app.workers.batch_worker
  ├── uv run python -m app.workers.analytics_flusher
  └── cloudflared tunnel run ...
```



Use:

```text
uv
Makefile
FastAPI
vLLM
Redis inside the Vast AI container
external Postgres
external ClickHouse
external Sentry
external Prometheus/Grafana
```

All commands must run through `uv run`.

The Makefile must become the main interface:

```bash
make install
make dev
make lint
make format
make test-unit
make test-integration
make test
make migrate
make run-api
make run-worker
make run-flusher
make run-vllm
make run-redis
make smoke
make bench
```

Testing rule:

```text
Every feature must be followed by:
1. minimal unit tests for that feature
2. one minimal integration test proving the feature works with previous layers
3. make lint
4. make test-unit
5. make test-integration
```

Do not write huge tests. Test only implemented behavior. No excessive mocking, no giant test matrix, no testing framework internals.

Redis decision:

```text
Run Redis inside the Vast AI container.
```

Reason: Redis is used for hot-path admission control, rate limits, token counters, concurrency counters, batch queue coordination, and overload flags. Putting it on your own server would add a network hop to the request-critical path for every inference request. Redis is runtime state, not durable source of truth, so colocating it with the GPU service is the correct v1 decision.

---

# Phase 0 — External infra prerequisites

This happens before coding the production path.

## 0.1 ClickHouse access

* [ ] Create dedicated ClickHouse user for this service.
* [ ] Restrict permissions to inference analytics DB/tables only.
* [ ] Verify connection from a test machine or Vast container.
* [ ] Verify insert.
* [ ] Verify select.
* [ ] Verify batch insert.
* [ ] Confirm timeout behavior.
* [ ] Save credentials as environment variables.

Done when:

```text
CLICKHOUSE_HOST=clickhouse.ansuman.yral.com works
test insert/select works
user is not overprivileged
```

## 0.2 Postgres access

* [ ] Create dedicated Postgres user.
* [ ] Create database/schema for inference service.
* [ ] Restrict permissions.
* [ ] Verify connection pooling.
* [ ] Verify read/write.
* [ ] Confirm network/firewall/Tailscale access.
* [ ] Save credentials as environment variables.

Done when:

```text
POSTGRES_DSN works
dedicated user can access only required tables
```

## 0.3 Sentry

* [ ] Create Sentry project: `gpu-inference-server` or `yral-gpu-inference`.
* [ ] Get DSN.
* [ ] Confirm test exception appears.
* [ ] Confirm payload scrubbing.

Done when:

```text
test exception appears with environment, release, and request_id
```

## 0.4 Prometheus/Grafana

* [ ] Run Prometheus/Grafana on `ansuman-1`.
* [ ] Prepare scrape config for FastAPI metrics.
* [ ] Prepare scrape config for vLLM metrics.
* [ ] Prepare scrape config for DCGM Exporter.
* [ ] Ensure scrape happens over private network/Tailscale.
* [ ] Do not expose `/metrics` publicly.

Done when:

```text
Prometheus can scrape private GPU container metrics over Tailscale
```

---

# Phase 1 — Repository foundation

## 1.1 Create Python project

* [ ] Initialize project with `uv`.
* [ ] Add FastAPI, Uvicorn, Pydantic Settings, httpx, asyncpg/SQLAlchemy, redis, clickhouse-connect, pytest, pytest-asyncio, ruff, mypy, sentry-sdk, prometheus-client.
* [ ] Create clean app structure:

```text
app/
  main.py
  core/
    config.py
    logging.py
    errors.py
    request_context.py
  api/
    routes/
  services/
    vllm/
    auth/
    rate_limit/
    quota/
    accounting/
    analytics/
    batch/
    observability/
  db/
    postgres.py
    migrations/
  workers/
  tests/
    unit/
    integration/
```

* [ ] Add `.env.example`.
* [ ] Add `Makefile`.
* [ ] Add `pyproject.toml`.

Minimal tests:

* [ ] Unit: settings load from env.
* [ ] Unit: app imports successfully.
* [ ] Integration: `GET /health` returns 200.

Validation:

```bash
make format
make lint
make test-unit
make test-integration
```

Done when:

```text
Project boots using uv and Makefile only.
```

---

# Phase 2 — Core FastAPI shell

## 2.1 App lifecycle and health

* [ ] Add FastAPI app factory.
* [ ] Add startup/shutdown hooks.
* [ ] Add `/health`.
* [ ] Add `/ready`.
* [ ] Add structured JSON logging.
* [ ] Add request ID middleware.
* [ ] Add global error response format.

Minimal tests:

* [ ] Unit: request ID generator returns unique IDs.
* [ ] Unit: error formatter returns OpenAI-style error object.
* [ ] Integration: `/health` and `/ready` work.

Done when:

```text
API shell is stable before adding inference logic.
```

---

# Phase 3 — vLLM adapter with fake upstream first

Do not connect real vLLM first. Build the contract against a fake local vLLM server.

## 3.1 vLLM client abstraction

* [ ] Create `VLLMClient`.
* [ ] Add non-streaming completion method.
* [ ] Add streaming completion method.
* [ ] Add timeout handling.
* [ ] Add upstream error mapping.
* [ ] Add cancellation support for streaming disconnects.

Minimal tests:

* [ ] Unit: request payload is forwarded correctly.
* [ ] Unit: upstream timeout maps to `504 upstream_timeout`.
* [ ] Unit: upstream 500 maps to `502 upstream_error`.
* [ ] Integration: fake vLLM returns a non-streaming response through adapter.

Done when:

```text
FastAPI can talk to fake vLLM through the same interface real vLLM will use.
```

---

# Phase 4 — OpenAI-compatible basic API

## 4.1 `/v1/models`

* [ ] Return configured model list.
* [ ] Keep response OpenAI-compatible.

Minimal tests:

* [ ] Unit: model config maps to response shape.
* [ ] Integration: `GET /v1/models` returns expected model ID.

## 4.2 `/v1/chat/completions` non-streaming

* [ ] Accept OpenAI-style chat completion payload.
* [ ] Validate required fields.
* [ ] Forward request to vLLM adapter.
* [ ] Return OpenAI-compatible response.
* [ ] Add `x-request-id`.

Minimal tests:

* [ ] Unit: invalid payload returns `400 bad_request`.
* [ ] Unit: valid payload creates normalized internal request.
* [ ] Integration: fake vLLM response returns through `/v1/chat/completions`.

Done when:

```text
OpenAI client can call non-streaming endpoint against fake vLLM.
```

---

# Phase 5 — SSE streaming

## 5.1 Streaming endpoint

* [ ] Support `stream=true`.
* [ ] Return `Content-Type: text/event-stream`.
* [ ] Add `Cache-Control: no-cache, no-transform`.
* [ ] Forward chunks immediately.
* [ ] Send final `data: [DONE]`.
* [ ] Track first-token time.
* [ ] Add heartbeat support.
* [ ] Detect client disconnect.
* [ ] Cancel upstream generation on disconnect.

Minimal tests:

* [ ] Unit: SSE chunk formatter is correct.
* [ ] Unit: heartbeat event is valid.
* [ ] Integration: fake streaming vLLM returns chunks through FastAPI.
* [ ] Integration: disconnect cleanup path runs without leaking request state.

Done when:

```text
Streaming works through FastAPI with correct SSE headers.
```

---

# Phase 6 — Postgres schema and API key auth

## 6.1 Migrations

* [ ] Add migration framework.
* [ ] Create `users`.
* [ ] Create `projects`.
* [ ] Create `api_keys`.
* [ ] Create `quota_policies`.
* [ ] Create `request_audit_records`.
* [ ] Create `batch_jobs`.

## 6.2 API key auth

* [ ] Use key format `sk_yral_...`.
* [ ] Store only key hash.
* [ ] Store prefix for lookup/debug.
* [ ] Add API key creation script.
* [ ] Add auth middleware.
* [ ] Attach auth context to request state.
* [ ] Reject missing key.
* [ ] Reject invalid key.
* [ ] Reject expired/revoked key.
* [ ] Enforce allowed models.

Minimal tests:

* [ ] Unit: raw key hashing works.
* [ ] Unit: invalid key returns `401`.
* [ ] Unit: disallowed model returns `403`.
* [ ] Integration: generated key can call `/v1/chat/completions`.
* [ ] Integration: revoked key cannot call endpoint.

Done when:

```text
No protected inference endpoint works without a valid Postgres-backed API key.
```

---

# Phase 7 — Redis runtime layer inside Vast container

## 7.1 Redis setup

* [ ] Add local Redis process to startup plan.
* [ ] Add Redis config/env.
* [ ] Add health check for Redis.
* [ ] Add fail-closed behavior when Redis is unavailable.
* [ ] Add Redis client wrapper.

## 7.2 Rate limits and concurrency

* [ ] Add RPM limit per API key.
* [ ] Add concurrent request limit per API key.
* [ ] Add TPM reservation placeholder.
* [ ] Add overload flag check.
* [ ] Use atomic Redis operations/Lua where needed.
* [ ] Ensure counters decrement in `finally`.

Minimal tests:

* [ ] Unit: rate limit key names are correct.
* [ ] Unit: concurrency counter increments/decrements.
* [ ] Unit: Redis unavailable maps to controlled `503 dependency_unavailable` or `503 server_overloaded`.
* [ ] Integration: exceeding RPM returns `429`.
* [ ] Integration: concurrent request limit returns `429`.
* [ ] Integration: failed request does not leak concurrency counter.

Done when:

```text
Redis protects GPU admission before any request reaches vLLM.
```

---

# Phase 8 — Token accounting and quota lifecycle

## 8.1 Token estimation

* [ ] Use tokenizer compatible with the served vLLM model family.
* [ ] Estimate prompt tokens before admission.
* [ ] Enforce max input tokens.
* [ ] Enforce max output tokens.
* [ ] Enforce max total tokens.

## 8.2 Quota reservation/finalization

* [ ] Reserve estimated tokens in Redis before forwarding.
* [ ] Count completion tokens during/after generation.
* [ ] Finalize actual usage.
* [ ] Release unused reservation.
* [ ] Handle failure.
* [ ] Handle client disconnect.
* [ ] Mark partial usage correctly.

Minimal tests:

* [ ] Unit: prompt token estimator is called before vLLM.
* [ ] Unit: max token violation returns `400` or `413`.
* [ ] Unit: quota reservation finalizes correctly on success.
* [ ] Unit: quota reservation finalizes correctly on failure.
* [ ] Integration: completed request writes correct usage.
* [ ] Integration: disconnected streaming request writes `client_disconnected`/partial usage.

Done when:

```text
Every request has accounting, including success, failure, timeout, and disconnect.
```

---

# Phase 9 — Request audit records in Postgres

## 9.1 Audit lifecycle

* [ ] Create audit record when request is accepted.
* [ ] Update final status on completion/failure/disconnect.
* [ ] Store request ID, user ID, project ID, API key ID, model, status, token counts, latency, error code.
* [ ] Do not store full prompts by default.
* [ ] Store prompt hash if needed.

Minimal tests:

* [ ] Unit: audit record builder excludes raw prompt and API key.
* [ ] Integration: success creates final audit record.
* [ ] Integration: upstream timeout creates failed audit record.
* [ ] Integration: client disconnect creates partial audit record.

Done when:

```text
Postgres has correctness-critical request history independent of ClickHouse.
```

---

# Phase 10 — ClickHouse analytics ingestion

## 10.1 ClickHouse schema

* [ ] Create `inference_analytics` database.
* [ ] Create `usage_events_local`.
* [ ] Create `usage_events` distributed table.
* [ ] Create `inference_events_local`.
* [ ] Create `inference_events` distributed table.

## 10.2 Event collector

* [ ] Add bounded in-memory queue.
* [ ] Add event models.
* [ ] Split critical and non-critical events.
* [ ] Never block request path on ClickHouse.
* [ ] Drop non-critical events when queue is full.
* [ ] Keep critical events recoverable through Postgres/local spool.

## 10.3 Batch flusher

* [ ] Flush every 1–5 seconds.
* [ ] Flush when batch size threshold is reached.
* [ ] Use batch inserts.
* [ ] Add retry with exponential backoff.
* [ ] Pause gracefully when ClickHouse is down.
* [ ] Add shutdown drain.

Minimal tests:

* [ ] Unit: event serialization matches ClickHouse schema.
* [ ] Unit: non-critical event drops when queue full.
* [ ] Unit: ClickHouse failure does not raise into request path.
* [ ] Integration: successful request queues analytics event.
* [ ] Integration: flusher writes batch to test ClickHouse or fake ClickHouse.
* [ ] Integration: ClickHouse down does not break inference endpoint.

Done when:

```text
Analytics are asynchronous, batched, and safe under ClickHouse failure.
```

---

# Phase 11 — Sentry integration

## 11.1 Sentry setup

* [ ] Initialize Sentry only when DSN exists.
* [ ] Add environment and release tags.
* [ ] Add request ID, user ID, project ID, API key ID, model, endpoint, stream flag.
* [ ] Scrub API keys, auth headers, prompts, DB credentials, tunnel tokens.
* [ ] Capture unhandled exceptions.
* [ ] Capture background worker failures.
* [ ] Capture ClickHouse flusher failures after retry threshold.
* [ ] Capture vLLM timeout/parsing failures.
* [ ] Do not capture normal 400/401/429 noise.

Minimal tests:

* [ ] Unit: Sentry scrubber removes secrets.
* [ ] Unit: expected 401/429 are not captured.
* [ ] Integration: forced exception is captured in test transport.
* [ ] Integration: Sentry unavailable does not break request.

Done when:

```text
Sentry helps debug failures but is never in the request-critical path.
```

---

# Phase 12 — Metrics endpoint

## 12.1 FastAPI metrics

* [ ] Add private `/metrics`.
* [ ] Add request count.
* [ ] Add latency histogram.
* [ ] Add TTFT histogram.
* [ ] Add active stream gauge.
* [ ] Add 429/503 counters.
* [ ] Add analytics queue size.
* [ ] Add ClickHouse flush failure counter.
* [ ] Add Redis failure counter.
* [ ] Add vLLM upstream error counter.

Minimal tests:

* [ ] Unit: metrics counters increment.
* [ ] Integration: `/metrics` exposes expected metric names.
* [ ] Integration: `/metrics` is not exposed through public Cloudflare route config.

Done when:

```text
Prometheus can observe app health without exposing metrics publicly.
```

---

# Phase 13 — Batch jobs

## 13.1 Batch API

* [ ] Add `POST /v1/batch/jobs`.
* [ ] Add `GET /v1/batch/jobs/{id}`.
* [ ] Add `POST /v1/batch/jobs/{id}/cancel`.
* [ ] Store batch job in Postgres.
* [ ] Enqueue job in Redis.
* [ ] Return job ID immediately.

## 13.2 Worker

* [ ] Worker pulls from Redis.
* [ ] Worker checks Postgres source of truth.
* [ ] Worker checks online load before sending to vLLM.
* [ ] Worker uses the same internal inference lifecycle as online requests.
* [ ] Worker records usage.
* [ ] Worker writes audit record.
* [ ] Worker emits ClickHouse analytics.
* [ ] Worker updates job status.

## 13.3 Recovery scanner

* [ ] Periodically find queued/runnable Postgres jobs not present in Redis.
* [ ] Re-enqueue safely.
* [ ] Avoid duplicate execution through locks/status transitions.

Minimal tests:

* [ ] Unit: batch status transitions are valid.
* [ ] Unit: worker does not run cancelled job.
* [ ] Unit: recovery scanner re-enqueues stuck queued job.
* [ ] Integration: submit job → worker processes → result stored.
* [ ] Integration: Redis enqueue failure still leaves recoverable Postgres job.
* [ ] Integration: batch path writes usage/audit/analytics like online path.

Done when:

```text
Batch jobs are durable through Postgres and coordinated through local Redis.
```

---

# Phase 14 — Real vLLM runtime wiring

## 14.1 vLLM process

* [ ] Add vLLM startup command.
* [ ] Bind vLLM to `127.0.0.1:8001`.
* [ ] Configure tensor parallel size = 4.
* [ ] Configure model path/name.
* [ ] Configure max model length.
* [ ] Configure GPU memory utilization.
* [ ] Configure max sequences and batched tokens.
* [ ] Expose vLLM metrics privately.
* [ ] Add readiness check.

## 14.2 FastAPI to vLLM

* [ ] Point adapter to `http://127.0.0.1:8001`.
* [ ] Verify `/v1/models`.
* [ ] Verify non-streaming.
* [ ] Verify streaming.
* [ ] Verify cancellation.

Minimal tests:

* [ ] Integration: real vLLM `/v1/models` responds.
* [ ] Integration: real non-streaming inference works.
* [ ] Integration: real streaming inference works.
* [ ] Integration: upstream timeout handled cleanly.

Done when:

```text
FastAPI talks to real local vLLM, and vLLM is not publicly exposed.
```

---

# Phase 15 — Cloudflare Tunnel wiring

## 15.1 Tunnel config

* [ ] Install/configure `cloudflared` inside Vast container.
* [ ] Route `nsfw-model.ansuman.yral.com` to `http://127.0.0.1:8000`.
* [ ] Do not route vLLM port.
* [ ] Do not route Redis.
* [ ] Do not route `/metrics`.
* [ ] Do not route admin/debug endpoints.
* [ ] Verify SSE streaming through tunnel.

Minimal tests:

* [ ] Smoke: public `/health` works.
* [ ] Smoke: public `/v1/models` works with auth where required.
* [ ] Smoke: public streaming response is not buffered.
* [ ] Smoke: direct vLLM port is unreachable publicly.
* [ ] Smoke: `/metrics` is unreachable publicly.

Done when:

```text
Only the OpenAI-compatible public API is exposed through Cloudflare Tunnel.
```

---

# Phase 16 — Container startup and supervision

## 16.1 Runtime process model

Inside the Vast Ubuntu container, run:

```text
redis-server
vLLM server
FastAPI gateway
batch worker
analytics flusher
cloudflared
DCGM exporter
```

* [ ] Add startup script.
* [ ] Add process supervisor.
* [ ] Add log files per process.
* [ ] Add restart policy.
* [ ] Add graceful shutdown.
* [ ] Add startup dependency order:

  1. Redis
  2. vLLM
  3. FastAPI
  4. workers/flusher
  5. cloudflared
  6. exporters

Minimal tests:

* [ ] Smoke: all processes start.
* [ ] Smoke: killing FastAPI restarts it.
* [ ] Smoke: killing worker restarts it.
* [ ] Smoke: graceful shutdown drains analytics queue.
* [ ] Smoke: Redis restart causes controlled temporary failure, not quota bypass.

Done when:

```text
Container can boot the full backend reliably from one command.
```

---

# Phase 17 — Observability dashboards

## 17.1 Grafana dashboards

* [ ] Gateway dashboard.
* [ ] vLLM dashboard.
* [ ] GPU dashboard.
* [ ] Redis dashboard.
* [ ] ClickHouse ingestion dashboard.
* [ ] Business usage dashboard from ClickHouse.

Minimum panels:

```text
requests/sec
success rate
error rate
429 rate
503 rate
p95 latency
p95 TTFT
active streams
tokens/sec
vLLM running requests
vLLM waiting requests
KV-cache usage
GPU memory
GPU utilization
analytics queue size
ClickHouse flush failures
client disconnects
```

Minimal tests:

* [ ] Smoke: Prometheus sees FastAPI metrics.
* [ ] Smoke: Prometheus sees vLLM metrics.
* [ ] Smoke: Prometheus sees GPU metrics.
* [ ] Smoke: Grafana dashboard loads.

Done when:

```text
You can see whether the service is healthy without SSHing into the box.
```

---

# Phase 18 — Load testing and capacity finding

## 18.1 Benchmark scripts

Create benchmark profiles:

```text
short prompt / short output
medium prompt / medium output
long prompt / short output
short prompt / long output
worst-case max input / max output
streaming
batch
mixed online + batch
```

Test concurrency:

```text
1
2
4
8
16
32
64
128
```

Record:

```text
requests/sec
tokens/sec
TTFT p50/p95/p99
latency p50/p95/p99
TPOT p50/p95/p99
GPU memory
KV-cache usage
OOMs
429s
503s
client disconnects
vLLM running/waiting requests
analytics queue lag
ClickHouse flush latency
```

Minimal tests:

* [ ] Unit: benchmark config parser works.
* [ ] Integration: benchmark script can run against local fake server.
* [ ] Smoke: benchmark script can run against real endpoint with small load.

Done when:

```text
You know the safe concurrency and overload threshold for the actual Vast GPU machine.
```

---

# Phase 19 — Overload policy

## 19.1 Admission control

Implement overload decisions in this order:

```text
1. reject/pause new batch jobs
2. pause batch workers
3. drop non-critical analytics events
4. reject low-priority online requests
5. reject all new online requests with 503
```

Signals:

```text
vLLM waiting requests too high
KV-cache usage too high
GPU memory too high
TTFT p95 too high
active streams too high
Redis counters too high
analytics queue too high
ClickHouse flush failures too high
```

Minimal tests:

* [ ] Unit: overload evaluator chooses correct action.
* [ ] Integration: overload flag rejects online request with `503`.
* [ ] Integration: overload pauses batch worker.
* [ ] Integration: overload does not corrupt quota counters.

Done when:

```text
The service fails fast instead of OOMing or hanging.
```

---

# Phase 20 — Reliability hardening

## 20.1 Failure paths

* [ ] Bad JSON does not crash app.
* [ ] Invalid auth does not hit vLLM.
* [ ] Redis down fails closed.
* [ ] Postgres down blocks correctness-critical requests safely.
* [ ] ClickHouse down does not break inference.
* [ ] Sentry down does not break inference.
* [ ] vLLM down returns controlled `502/503`.
* [ ] Client disconnect cancels upstream generation.
* [ ] Batch worker cannot overwhelm online traffic.
* [ ] Shutdown drains analytics flusher.
* [ ] Startup warms model.

Minimal tests:

* [ ] Integration: Redis down → controlled 503.
* [ ] Integration: ClickHouse down → request still succeeds.
* [ ] Integration: vLLM down → controlled upstream error.
* [ ] Integration: client disconnect → no leaked concurrency counter.
* [ ] Integration: graceful shutdown drains queue.

Done when:

```text
Known dependency failures have predictable behavior.
```

---

# Final acceptance checklist

The final checkbox can only be marked when all of this is true:

* [ ] Project uses `uv`.
* [ ] All commands go through `Makefile`.
* [ ] `make lint` passes.
* [ ] `make format` passes.
* [ ] `make test-unit` passes.
* [ ] `make test-integration` passes.
* [ ] FastAPI runs inside Vast container.
* [ ] vLLM runs inside same Vast container.
* [ ] Redis runs inside same Vast container.
* [ ] Cloudflare Tunnel points only to FastAPI.
* [ ] vLLM is localhost-only.
* [ ] `/metrics` is private.
* [ ] API key auth works.
* [ ] Redis rate limiting works.
* [ ] Redis concurrency limiting works.
* [ ] Token accounting works.
* [ ] Client disconnect accounting works.
* [ ] Postgres audit records work.
* [ ] ClickHouse batched analytics works.
* [ ] ClickHouse failure does not break inference.
* [ ] Sentry captures real app failures.
* [ ] Sentry outage does not break inference.
* [ ] Batch jobs use the same lifecycle as online requests.
* [ ] Batch recovery scanner works.
* [ ] Prometheus scrapes app/vLLM/GPU metrics.
* [ ] Grafana dashboards show health.
* [ ] Benchmark scripts produce safe concurrency numbers.
* [ ] Overload policy prevents OOM.
* [ ] Public endpoint behaves like OpenAI-compatible API.
* [ ] OpenAI SDK can call the server by changing `base_url`, `api_key`, and `model`.

Final state:

```text
The server is production-style for one Vast AI GPU node.
It is not HA yet.
It can serve GPU inference behind Cloudflare Tunnel.
It has auth, quota, Redis admission control, Postgres correctness, ClickHouse analytics, Sentry errors, Prometheus/Grafana metrics, batch jobs, and benchmarked capacity.
```
