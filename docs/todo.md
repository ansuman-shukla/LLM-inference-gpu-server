
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
    model.ansuman.yral.com -> http://127.0.0.1:8000

External:
  Postgres:
    127.0.0.1:15432 / 127.0.0.1:15433 inside Vast
    forwarded over Tailscale to 100.78.17.101:15432 / 100.79.99.107:15432

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
make run-recovery
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

* [x] Create dedicated ClickHouse user for this service.
* [x] Restrict permissions to inference analytics DB/tables only.
* [x] Verify connection from a test machine.
* [x] Allow `8443/tcp` on `tailscale0` from tailnet sources in UFW on ansuman-1 and ansuman-2.
* [ ] Verify insert.
* [x] Verify select.
* [ ] Verify batch insert.
* [ ] Confirm timeout behavior.
* [x] Save credentials as environment variables in local ignored `.env`.

Done when:

```text
CLICKHOUSE_URL=https://100.78.17.101:8443 works
test insert/select works
user is not overprivileged
```

## 0.2 Postgres access

* [x] Add HAProxy Postgres TCP listener on ansuman-1 Tailscale IP `100.78.17.101:15432`.
* [x] Add HAProxy Postgres TCP listener on ansuman-2 Tailscale IP `100.79.99.107:15432`.
* [x] Verify ansuman-1 is PostgreSQL primary and ansuman-2 is standby with `pg_is_in_recovery()`.
* [x] Allow `15432/tcp` on `tailscale0` from tailnet sources in UFW on ansuman-1 and ansuman-2.
* [x] Create dedicated Postgres user.
* [x] Create database/schema for inference service.
* [x] Restrict permissions.
* [ ] Verify connection pooling.
* [x] Verify read/write.
* [x] Confirm network/firewall/Tailscale access from current tailnet machine.
* [x] Install and join Tailscale on the Vast instance through the deploy script.
* [x] Store SQLAlchemy asyncpg multi-host DSN with both HAProxy listener IPs in local ignored `.env`.
* [x] Add `asyncpg` runtime dependency with the SQLAlchemy DB layer.
* [x] Tighten SQLAlchemy lower bound to `>=2.0.18` when DB code lands.
* [x] Save credentials as environment variables in local ignored `.env`.

Done when:

```text
DATABASE_URL works through local Vast forwards to 100.78.17.101:15432 and 100.79.99.107:15432
dedicated user can access only required tables
```

## 0.3 Sentry

* [x] Create Sentry project.
* [x] Get DSN.
* [x] Save DSN in local ignored `.env`.
* [x] Wire `sentry-sdk` initialization into FastAPI startup/config.
* [ ] Confirm test exception appears.
* [x] Confirm payload scrubbing.

Done when:

```text
test exception appears with environment, release, and request_id
```

## 0.4 Prometheus/Grafana (deferred)

Do later. This is intentionally not part of the immediate Vast bootstrap.

* [ ] Run Prometheus/Grafana on `ansuman-1`.
* [x] Prepare scrape config for FastAPI metrics.
* [ ] Prepare scrape config for vLLM metrics.
* [ ] Prepare scrape config for DCGM Exporter.
* [ ] Ensure scrape happens over private network/Tailscale.
* [x] Do not expose `/metrics` publicly.

Done when:

```text
Prometheus can scrape private GPU container metrics over Tailscale
```

---

# Phase 1 — Repository foundation

## 1.1 Create Python project

* [x] Initialize project with `uv`.
* [x] Add FastAPI, Uvicorn, Pydantic Settings, httpx, asyncpg/SQLAlchemy, redis, clickhouse-connect, pytest, pytest-asyncio, ruff, mypy, sentry-sdk, prometheus-client.
* [x] Create clean app structure:

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

* [x] Add `.env.example`.
* [x] Add `Makefile`.
* [x] Add `pyproject.toml`.

Minimal tests:

* [x] Unit: settings load from env.
* [x] Unit: app imports successfully.
* [x] Integration: `GET /health` returns 200.

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

* [x] Add FastAPI app factory.
* [x] Add startup/shutdown hooks.
* [x] Add `/health`.
* [x] Add `/ready`.
* [x] Add structured JSON logging.
* [x] Add request ID middleware.
* [x] Add global error response format.

Minimal tests:

* [x] Unit: request ID generator returns unique IDs.
* [x] Unit: error formatter returns OpenAI-style error object.
* [x] Integration: `/health` and `/ready` work.

Done when:

```text
API shell is stable before adding inference logic.
```

---

# Phase 3 — vLLM adapter with fake upstream first

Do not connect real vLLM first. Build the contract against a fake local vLLM server.

## 3.1 vLLM client abstraction

* [x] Create `VLLMClient`.
* [x] Add non-streaming completion method.
* [x] Add streaming completion method.
* [x] Add timeout handling.
* [x] Add upstream error mapping.
* [x] Add cancellation support for streaming disconnects.

Minimal tests:

* [x] Unit: request payload is forwarded correctly.
* [x] Unit: upstream timeout maps to `504 upstream_timeout`.
* [x] Unit: upstream 500 maps to `502 upstream_error`.
* [x] Integration: fake vLLM returns a non-streaming response through adapter.

Done when:

```text
FastAPI can talk to fake vLLM through the same interface real vLLM will use.
```

---

# Phase 4 — OpenAI-compatible basic API

## 4.1 `/v1/models`

* [x] Return configured model list.
* [x] Keep response OpenAI-compatible.

Minimal tests:

* [x] Unit: model config maps to response shape.
* [x] Integration: `GET /v1/models` returns expected model ID.

## 4.2 `/v1/chat/completions` non-streaming

* [x] Accept OpenAI-style chat completion payload.
* [x] Validate required fields.
* [x] Forward request to vLLM adapter.
* [x] Return OpenAI-compatible response.
* [x] Add `x-request-id`.

Minimal tests:

* [x] Unit: invalid payload returns `400 bad_request`.
* [x] Unit: valid payload creates normalized internal request.
* [x] Integration: fake vLLM response returns through `/v1/chat/completions`.

Done when:

```text
OpenAI client can call non-streaming endpoint against fake vLLM.
```

---

# Phase 5 — SSE streaming

## 5.1 Streaming endpoint

* [x] Support `stream=true`.
* [x] Return `Content-Type: text/event-stream`.
* [x] Add `Cache-Control: no-cache, no-transform`.
* [x] Forward chunks immediately.
* [x] Send final `data: [DONE]`.
* [x] Track first-token time.
* [x] Add heartbeat support.
* [x] Detect client disconnect.
* [x] Cancel upstream generation on disconnect.

Minimal tests:

* [x] Unit: SSE chunk formatter is correct.
* [x] Unit: heartbeat event is valid.
* [x] Integration: fake streaming vLLM returns chunks through FastAPI.
* [x] Integration: disconnect cleanup path runs without leaking request state.

Done when:

```text
Streaming works through FastAPI with correct SSE headers.
```

---

# Phase 6 — Postgres schema and API key auth

## 6.1 Migrations

* [x] Add migration framework.
* [x] Create `users`.
* [x] Create `projects`.
* [x] Create `api_keys`.
* [x] Create `quota_policies`.
* [x] Create `request_audit_records`.
* [x] Create `batch_jobs`.

## 6.2 API key auth

* [x] Use key format `an_...`.  // changed from sk_yral_.. -> an_...
* [x] Store only key hash.
* [x] Store prefix for lookup/debug.
* [x] Add API key creation script.
* [x] Add auth middleware.
* [x] Attach auth context to request state.
* [x] Reject missing key.
* [x] Reject invalid key.
* [x] Reject expired/revoked key.
* [x] Enforce allowed models.

Minimal tests:

* [x] Unit: raw key hashing works.
* [x] Unit: invalid key returns `401`.
* [x] Unit: disallowed model returns `403`.
* [x] Integration: generated key can call `/v1/chat/completions`.
* [x] Integration: revoked key cannot call endpoint.

Implementation notes for future sessions:

```text
Phase 6 follows this TODO's `an_...` API key prefix, not the older `sk_yral_...`
text still present in docs/plan.md. The prefix is controlled by API_KEY_PREFIX
and defaults to `an`.

Production auth is Postgres-backed through SQLAlchemy async sessions and the
`api_keys.key_hash` column. Local integration tests inject StaticApiKeyAuthService
so they do not require live Postgres.

Auth middleware renders AppError responses directly because Starlette
BaseHTTPMiddleware wraps middleware-raised exceptions before FastAPI exception
handlers can render the existing OpenAI-style error object.
```

Done when:

```text
No protected inference endpoint works without a valid Postgres-backed API key.
```

---

# Phase 7 — Redis runtime layer inside Vast container

## 7.1 Redis setup

* [x] Add local Redis process to startup plan.
* [x] Add Redis config/env.
* [x] Add health check for Redis.
* [x] Add fail-closed behavior when Redis is unavailable.
* [x] Add Redis client wrapper.

## 7.2 Rate limits and concurrency

* [x] Add RPM limit per API key.
* [x] Add concurrent request limit per API key.
* [x] Add TPM reservation placeholder.
* [x] Add overload flag check.
* [x] Use atomic Redis operations/Lua where needed.
* [x] Ensure counters decrement in `finally`.

Minimal tests:

* [x] Unit: rate limit key names are correct.
* [x] Unit: concurrency counter increments/decrements.
* [x] Unit: Redis unavailable maps to controlled `503 dependency_unavailable` or `503 server_overloaded`.
* [x] Integration: exceeding RPM returns `429`.
* [x] Integration: concurrent request limit returns `429`.
* [x] Integration: failed request does not leak concurrency counter.

Implementation notes for future sessions:

```text
Redis admission is lazy-created on the first protected inference request unless
an admission_service is injected by tests. /ready pings Redis only after the
redis_client exists in app.state, so local health tests do not require Redis.

The Phase 7 implementation uses Redis INCR/DECR/EXPIRE directly. If limits need
strong multi-key atomicity later, replace the admission sequence with Lua without
changing the route contract: admission_service.admit(...) returns a lease and the
route releases it in finally/stream close.
```

Done when:

```text
Redis protects GPU admission before any request reaches vLLM.
```

---

# Phase 8 — Token accounting and quota lifecycle

## 8.1 Token estimation

* [x] Use tokenizer compatible with the served vLLM model family.
* [x] Estimate prompt tokens before admission.
* [x] Enforce max input tokens.
* [x] Enforce max output tokens.
* [x] Enforce max total tokens.

## 8.2 Quota reservation/finalization

* [x] Reserve estimated tokens in Redis before forwarding.
* [x] Count completion tokens during/after generation.
* [x] Finalize actual usage.
* [x] Release unused reservation.
* [x] Handle failure.
* [x] Handle client disconnect.
* [x] Mark partial usage correctly.

Minimal tests:

* [x] Unit: prompt token estimator is called before vLLM.
* [x] Unit: max token violation returns `400` or `413`.
* [x] Unit: quota reservation finalizes correctly on success.
* [x] Unit: quota reservation finalizes correctly on failure.
* [x] Integration: completed request writes correct usage.
* [x] Integration: disconnected streaming request writes `client_disconnected`/partial usage.

Implementation notes for future sessions:

```text
The token path uses a TokenEstimator interface and a conservative default
HeuristicTokenEstimator. Swap app.state.token_estimator for the exact served
model tokenizer when the final vLLM model is pinned; the route and quota
reservation contracts already pass through the estimator abstraction.

Redis TPM reservation stores estimated total tokens in rl:api_key:{id}:tpm before
vLLM and releases unused tokens on success, failure, and stream close. Usage is
currently recorded in request.state.usage/app.state.usage_records; Phase 9 should
persist the same UsageRecord into Postgres audit rows.
```

Done when:

```text
Every request has accounting, including success, failure, timeout, and disconnect.
```

---

# Phase 9 — Request audit records in Postgres

## 9.1 Audit lifecycle

* [x] Create audit record when request is accepted.
* [x] Update final status on completion/failure/disconnect.
* [x] Store request ID, user ID, project ID, API key ID, model, status, token counts, latency, error code.
* [x] Do not store full prompts by default.
* [x] Store prompt hash if needed.

Minimal tests:

* [x] Unit: audit record builder excludes raw prompt and API key.
* [x] Integration: success creates final audit record.
* [x] Integration: upstream timeout creates failed audit record.
* [x] Integration: client disconnect creates partial audit record.

Implementation notes for future sessions:

```text
Production audit lifecycle uses RequestAuditService with SQLAlchemy async sessions
and request_audit_records. Tests inject InMemoryRequestAuditService, so local test
runs do not require live Postgres.

Audit start data stores prompt_hash only. Raw prompts and raw API keys are not
part of AuditStart or RequestAuditRecord.
```

Done when:

```text
Postgres has correctness-critical request history independent of ClickHouse.
```

---

# Phase 10 — ClickHouse analytics ingestion

## 10.1 ClickHouse schema

* [x] Create `inference_analytics` database.
* [x] Create `usage_events_local`.
* [x] Create `usage_events` distributed table.
* [x] Create `inference_events_local`.
* [x] Create `inference_events` distributed table.

## 10.2 Event collector

* [x] Add bounded in-memory queue.
* [x] Add event models.
* [x] Split critical and non-critical events.
* [x] Never block request path on ClickHouse.
* [x] Drop non-critical events when queue full.
* [x] Keep critical events recoverable through Postgres/local spool.

## 10.3 Batch flusher

* [x] Flush every 1–5 seconds.
* [x] Flush when batch size threshold is reached.
* [x] Use batch inserts.
* [x] Add retry with exponential backoff.
* [x] Pause gracefully when ClickHouse is down.
* [x] Add shutdown drain.

Minimal tests:

* [x] Unit: event serialization matches ClickHouse schema.
* [x] Unit: non-critical event drops when queue full.
* [x] Unit: ClickHouse failure does not raise into request path.
* [x] Integration: successful request queues analytics event.
* [x] Integration: flusher writes batch to test ClickHouse or fake ClickHouse.
* [x] Integration: ClickHouse down does not break inference endpoint.

Implementation notes for future sessions:

```text
Request handling only calls AnalyticsCollector.collect(...) inside a swallow-errors
helper. ClickHouse inserts happen in ClickHouseFlusher batches outside the request
path.

backend/scripts/create_clickhouse_tables.py owns the Phase 10 DDL. Set
CLICKHOUSE_CLUSTER to the real ClickHouse cluster name before running it; the
current default is `default` only as a local placeholder.

Critical analytics events are spooled to local JSONL when the bounded queue is
full. Request audit records in Postgres remain the correctness source for
critical usage recovery.
```

Done when:

```text
Analytics are asynchronous, batched, and safe under ClickHouse failure.
```

---

# Phase 11 — Sentry integration

## 11.1 Sentry setup

* [x] Initialize Sentry only when DSN exists.
* [x] Add environment and release tags.
* [x] Add request ID, user ID, project ID, API key ID, model, endpoint, stream flag.
* [x] Scrub API keys, auth headers, prompts, DB credentials, tunnel tokens.
* [x] Capture unhandled exceptions.
* [x] Capture background worker failures.
* [x] Capture ClickHouse flusher failures after retry threshold.
* [x] Capture vLLM timeout/parsing failures.
* [x] Do not capture normal 400/401/429 noise.

Minimal tests:

* [x] Unit: Sentry scrubber removes secrets.
* [x] Unit: expected 401/429 are not captured.
* [x] Integration: forced exception is captured in test transport.
* [x] Integration: Sentry unavailable does not break request.

Implementation notes for future sessions:

```text
Sentry lives in backend/services/observability/sentry.py. It no-ops unless
initialize_sentry(...) succeeds with a configured SENTRY_DSN, and capture calls are
wrapped so Sentry outage/capture failure cannot change API behavior.

Request exception capture is idempotent per request via
request.state.sentry_exception_captured. Route-level capture preserves model/stream
tags for vLLM failures; the global error handler covers unhandled/server errors.

The scrubber redacts auth headers, raw `an_...`/`sk-...` keys, prompt/message/input
payload fields, DB URL credentials, passwords/secrets/tokens, and tunnel tokens.
It intentionally preserves api_key_id because that is a safe identifier needed for
debugging.

Tests force SENTRY_DSN empty in tests/conftest.py so a developer's local ignored
.env cannot accidentally send test failures to the real self-hosted Sentry. Tests
that need Sentry use injected Settings plus a fake SDK.

backend/workers/batch_worker.py has Phase 11 process-level Sentry wrapping;
Phase 13 now adds the actual batch worker loop on top of it.
```

Done when:

```text
Sentry helps debug failures but is never in the request-critical path.
```

---

# Phase 12 — Metrics endpoint

## 12.1 FastAPI metrics

* [x] Add private `/metrics`.
* [x] Add request count.
* [x] Add latency histogram.
* [x] Add TTFT histogram.
* [x] Add active stream gauge.
* [x] Add 429/503 counters.
* [x] Add analytics queue size.
* [x] Add ClickHouse flush failure counter.
* [x] Add Redis failure counter.
* [x] Add vLLM upstream error counter.

Minimal tests:

* [x] Unit: metrics counters increment.
* [x] Integration: `/metrics` exposes expected metric names.
* [x] Integration: `/metrics` is not exposed through public Cloudflare route config.

Implementation notes for future sessions:

```text
Prometheus metrics live in backend/services/observability/metrics.py and use a
dedicated CollectorRegistry. MetricsMiddleware records request count/latency and
skips /metrics itself. Error responses include x-error-code so 429/503 counters
can label the app error code.

infra/cloudflared/config.yml.example explicitly blocks path: /metrics before the
general public FastAPI route. Keep that rule ordering in the real Cloudflare
Tunnel config; Cloudflare should expose only the OpenAI-compatible public API.

The /metrics endpoint exposes the FastAPI process registry. If analytics_flusher
or batch_worker run as separate processes, their process-local counters will need
their own private metrics endpoint or another aggregation path to be scraped.
```

Done when:

```text
Prometheus can observe app health without exposing metrics publicly.
```

---

# Phase 13 — Batch jobs

## 13.1 Batch API

* [x] Add `POST /v1/batch/jobs`.
* [x] Add `GET /v1/batch/jobs/{id}`.
* [x] Add `POST /v1/batch/jobs/{id}/cancel`.
* [x] Store batch job in Postgres.
* [x] Enqueue job in Redis.
* [x] Return job ID immediately.

## 13.2 Worker

* [x] Worker pulls from Redis.
* [x] Worker checks Postgres source of truth.
* [x] Worker checks online load before sending to vLLM.
* [x] Worker uses the same internal inference lifecycle as online requests.
* [x] Worker records usage.
* [x] Worker writes audit record.
* [x] Worker emits ClickHouse analytics.
* [x] Worker updates job status.

## 13.3 Recovery scanner

* [x] Periodically find queued/runnable Postgres jobs not present in Redis.
* [x] Re-enqueue safely.
* [x] Avoid duplicate execution through locks/status transitions.

Minimal tests:

* [x] Unit: batch status transitions are valid.
* [x] Unit: worker does not run cancelled job.
* [x] Unit: recovery scanner re-enqueues stuck queued job.
* [x] Integration: submit job → worker processes → result stored.
* [x] Integration: Redis enqueue failure still leaves recoverable Postgres job.
* [x] Integration: batch path writes usage/audit/analytics like online path.

Implementation notes for future sessions:

```text
Batch API routes are wired in backend/api/routes/batch_jobs.py and protected by
the existing API-key middleware. The MVP accepts one non-streaming chat-completion
payload per job; stream=true is rejected. It does not implement uploaded JSONL or
multi-request batch files yet.

The existing Phase 6 batch_jobs schema does not have dedicated input_payload or
result_payload columns from docs/plan.md, so Phase 13 stores input_payload,
result_payload, usage, and timestamps inside batch_jobs.metadata_json. Add a
future migration with first-class columns if queryability or large payload storage
matters.

Worker execution is in backend/services/batch/batch_worker.py and uses the same
service interfaces as online non-streaming requests: token planning, Redis
admission/quota lease, request audit, vLLM client, usage finalization, analytics
event emission, and Sentry capture. It is non-streaming only.

The worker supports an injectable should_run_job hook for online-load policy. The
default worker entrypoint currently relies on AdmissionService's Redis overload
check; richer vLLM/GPU load checks remain Phase 19 capacity/overload work.

Redis enqueue failure after Postgres job creation intentionally returns a queued
job. backend/services/batch/recovery_scanner.py re-enqueues queued jobs missing
from Redis. Use make run-recovery to run that scanner loop.

Job terminal status is `succeeded`/`failed`/`cancelled` in the batch_jobs row and
API response. If product API compatibility later needs `completed`, adjust the
status vocabulary and tests together.
```

Done when:

```text
Batch jobs are durable through Postgres and coordinated through local Redis.
```

---

# Phase 14 — Real vLLM runtime wiring

## 14.1 vLLM process

* [x] Add vLLM startup command.
* [x] Bind vLLM to `127.0.0.1:8001`.
* [x] Configure tensor parallel size = 4.
* [x] Configure model path/name.
* [x] Configure max model length.
* [x] Configure GPU memory utilization.
* [x] Configure max sequences and batched tokens.
* [x] Expose vLLM metrics privately.
* [x] Add readiness check.

## 14.2 FastAPI to vLLM

* [x] Point adapter to `http://127.0.0.1:8001`.
* [x] Verify `/v1/models`.
* [x] Verify non-streaming.
* [x] Verify streaming.
* [x] Verify cancellation.

Minimal tests:

* [x] Integration: real vLLM `/v1/models` responds.
* [x] Integration: real non-streaming inference works.
* [x] Integration: real streaming inference works.
* [x] Integration: upstream timeout handled cleanly.

Implementation notes for future sessions:

```text
Phase 14 is implemented in commit ea7cdf5. Runtime config lives in Settings as
VLLM_* variables; make run-vllm executes backend.scripts.run_vllm, which builds a
localhost-only `vllm serve` command for 127.0.0.1:8001 with tensor_parallel_size=4.

The optional real-vLLM pytest uses REAL_VLLM_BASE_URL and is skipped locally unless
that env var is set. Vast smoke checks on 2026-05-29 used the existing bootstrap
vLLM at 127.0.0.1:18000: /v1/models, a 1-token non-streaming request, and a
1-token streaming request all responded. Longer 4-token probes initially exceeded
30 seconds, so use a longer timeout for remote smoke tests on this instance.

vLLM metrics stay private because vLLM binds to localhost only; Prometheus should
scrape through a private/Tailscale path once Phase 17 observability resumes.
```

Done when:

```text
FastAPI talks to real local vLLM, and vLLM is not publicly exposed.
```

---

# Phase 15 — Cloudflare Tunnel wiring

## 15.1 Tunnel config

* [x] Install/configure `cloudflared` inside Vast container.
* [x] Route `model.ansuman.yral.com` to FastAPI through the live Caddy `:8000` route.
* [x] Do not route vLLM port.
* [x] Do not route Redis.
* [x] Do not route `/metrics`.
* [x] Do not route admin/debug endpoints.
* [ ] Verify SSE streaming through tunnel.

Minimal tests:

* [x] Smoke: public `/health` works.
* [x] Smoke: public `/docs` and `/openapi.json` work.
* [x] Smoke: public `/v1/models` works with auth where required.
* [x] Smoke: public authenticated `/v1/chat/completions` works.
* [ ] Smoke: public streaming response is not buffered.
* [x] Smoke: direct vLLM port is unreachable publicly.
* [x] Smoke: `/metrics` is unreachable publicly.

Implementation notes for future sessions:

```text
Phase 15 repo config is in infra/cloudflared/config.yml.example. It uses the real
hostname model.ansuman.yral.com, forwards only to http://127.0.0.1:8000, and
blocks /metrics, /admin, and /debug before the public route. Tests in
tests/integration/test_cloudflared_config.py assert the config does not mention
8001 or 6379.

Vast already had cloudflared 2026.5.0 installed during the 2026-05-29 check, but
the observed processes were Vast portal quick tunnels under
/opt/portal-aio/tunnel_manager, not the named Cloudflare tunnel for this app.
The deploy workflow now uploads CLOUDFLARED_TOKEN as a token file, and
infra/vast/deploy-release.sh installs /etc/cloudflared/token plus the repository
config before supervisor starts cloudflared. Public smoke on 2026-06-01 passes
through https://model.ansuman.yral.com: /health returns 200, /docs returns
Swagger UI, /openapi.json advertises BearerAuth, /v1/models returns
Qwen/Qwen3.6-27B-FP8, authenticated /v1/chat/completions returns 200, and /metrics
returns 404. The live Cloudflare token config still targets localhost:8000, so
the Vast Caddy :8000 block has a narrow gpu-inference route that forwards
API/docs paths to FastAPI on 127.0.0.1:8002 and leaves non-API portal-generated
behavior intact.
```

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

* [x] Add startup script.
* [x] Add process supervisor.
* [x] Add log files per process.
* [x] Add restart policy.
* [x] Add graceful shutdown.
* [x] Add startup dependency order:

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

Implementation notes for future sessions:

```text
Phase 16 supervisor config is infra/supervisord.conf and the one-command entrypoint
is infra/vast/startup.sh. The script defaults APP_DIR=/app, creates
/var/log/gpu-inference, and execs supervisord.

Supervisor priorities encode startup order: redis=10, vllm=20, api=30,
batch-worker=40, recovery-scanner=41, analytics-flusher=42, cloudflared=50,
dcgm-exporter=60. API, batch worker, and cloudflared wait on readiness helpers
before execing their long-running command. All app Python commands run through
uv run --env-file /app/.env.

Per-process stdout/stderr logs go to /var/log/gpu-inference/*.log. Programs use
TERM with stopasgroup/killasgroup; the analytics flusher entrypoint now handles
SIGTERM/SIGINT and calls ClickHouseFlusher.stop() for a final drain attempt.

Vast has supervisord available at /opt/sys-venv/shim/supervisord. The GitHub
deploy path now installs Redis, supervisor, cloudflared, Tailscale, socat, and
fuser/psmisc if missing, syncs the Python environment, runs Alembic migrations
over local Tailscale Postgres forwards, updates /app, stops supervisor, clears
stale FastAPI/vLLM listeners on 127.0.0.1:8000 and 127.0.0.1:8001, then waits for
local /health. The Phase 16 smoke items remain pending until rerun against the
latest deploy. DCGM exporter is still optional and may be absent from the base
container image.
```

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
* [x] Invalid auth does not hit vLLM.
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
* [x] FastAPI runs inside Vast container.
* [x] vLLM runs inside same Vast container.
* [x] Redis runs inside Vast container.
* [ ] Cloudflare Tunnel points only to FastAPI.
* [ ] vLLM is localhost-only.
* [x] `/metrics` is private.
* [x] API key auth works.
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
* [x] Public endpoint behaves like OpenAI-compatible API.
* [ ] OpenAI SDK can call the server by changing `base_url`, `api_key`, and `model`.

Final state:

```text
The server is production-style for one Vast AI GPU node.
It is not HA yet.
It can serve GPU inference behind Cloudflare Tunnel.
It has auth, quota, Redis admission control, Postgres correctness, ClickHouse analytics, Sentry errors, Prometheus/Grafana metrics, batch jobs, and benchmarked capacity.
```
