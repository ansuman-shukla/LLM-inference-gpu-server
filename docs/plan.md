
# Implementation Plan: Production-Style GPU Inference Server

Assumption: you have **one Vast AI host with 4 GPUs**, connected through **Cloudflare Tunnel**, serving:

```text
https://nsfw-model.ansuman.yral.com
```

You want to run one large model across the 4 GPUs as **one logical inference worker**.

---

# Phase 0: Infrastructure prerequisites

Before deploying the GPU inference server, prepare the external infrastructure that the GPU container will depend on.

## 0.1 ClickHouse prerequisite

Use the existing ClickHouse cluster:

```text
clickhouse.ansuman.yral.com
```

Create a dedicated ClickHouse user for the GPU inference service.

The ClickHouse user should have only the permissions needed for inference analytics tables.

Use ClickHouse Connect Python SDK from the FastAPI gateway / analytics flusher.

Validate before GPU deployment:

```text
GPU service can connect to ClickHouse
test insert works
test select works
batch insert works
connection timeout behavior is understood
ClickHouse user is not overprivileged
```

ClickHouse remains external to the GPU server.

The GPU server should not run ClickHouse locally.

## 0.2 Postgres prerequisite

Use the existing external Postgres server:

```text
postgress.ansuman.yral.com
```

Create a dedicated Postgres user for the GPU inference service.

Postgres should store:

```text
users/projects references if needed
api_keys
quota policies
batch_jobs
request_audit_records
webhook configs
critical usage records
```

Validate before GPU deployment:

```text
GPU service can connect to Postgres
dedicated user can read/write required tables
dedicated user cannot access unrelated databases/tables
connection pooling works
network/firewall access is restricted
TLS/private-network access is configured if possible
```

Postgres remains external to the GPU server.

The GPU server should not run Postgres locally.

## 0.3 Tailscale private network prerequisite

Set up Tailscale connectivity between:

```text
GPU Vast container
ansuman-1
ansuman-2
ansuman-3
Postgres server if possible
ClickHouse server if possible
Prometheus/Grafana server
```

Use Tailscale/private networking for internal metrics and admin access wherever possible.

Metrics endpoints should not be exposed publicly.

Cloudflare Tunnel should expose only the public inference API.

Internal/private routes should stay on Tailscale.

## 0.4 Prometheus/Grafana prerequisite

Host Prometheus and Grafana on one of the existing servers first.

Recommended MVP:

```text
ansuman-1
  - Prometheus
  - Grafana
```

Optional later:

```text
ansuman-2
  - standby Prometheus/Grafana
  - or second Prometheus scraper

ansuman-3
  - future Loki / alerting / backup observability node
```

Prometheus should scrape the GPU server over Tailscale.

Initial scrape targets:

```text
FastAPI metrics
vLLM metrics
NVIDIA DCGM Exporter metrics
Node/system metrics if available
Redis metrics if used
ClickHouse ingestion metrics exposed by the app
```

Grafana should show:

```text
GPU utilization
GPU memory
GPU temperature
vLLM running/waiting requests
KV-cache usage
tokens/sec
TTFT
request latency
error rate
429/503 rate
active streams
ClickHouse flusher health
analytics queue size
```

Do not expose Prometheus or Grafana publicly unless protected.

## 0.5 Sentry prerequisite

Use the existing self-hosted Sentry instance.

Create a dedicated Sentry project:

```text
gpu-inference-server
```

or:

```text
yral-gpu-inference
```

Configure the GPU service to report:

```text
application exceptions
background worker failures
ClickHouse flusher failures
Postgres/Redis connectivity failures
vLLM upstream failures
quota/accounting bugs
streaming cleanup bugs
deployment regressions
```

Validate before GPU deployment:

```text
test exception appears in Sentry
environment is tagged correctly
release/version is tagged correctly
request_id appears in Sentry events
sensitive payloads are not sent
Sentry outage does not break app execution
```

## 0.6 Final prerequisite success criteria

Before deploying the actual GPU inference server, confirm:

```text
ClickHouse user exists and connection works
Postgres user exists and connection works
Sentry project exists and test event works
Prometheus/Grafana server is running
Tailscale connectivity works between observability server and GPU container
metrics ports are private
public Cloudflare route exposes only FastAPI public API
secrets are ready as environment variables
```

---

## Final call

Your updated implementation order should be:

```text
1. Prepare ClickHouse user and test ClickHouse connection.
2. Prepare Postgres user and test Postgres connection.
3. Set up Tailscale network between GPU container and your servers.
4. Set up Prometheus/Grafana on ansuman-1 first.
5. Add Sentry project for gpu-inference-server.
6. Only then deploy the Vast GPU container with vLLM + FastAPI + cloudflared + exporters.
```

This is a better plan than deploying the GPU server first and then discovering that metrics, database access, Sentry, or analytics are not reachable.

[1]: https://prometheus.io/docs/prometheus/latest/configuration/configuration/?utm_source=chatgpt.com "Configuration"
[2]: https://tailscale.com/docs/reference/examples/acls?utm_source=chatgpt.com "ACL policy examples"
[3]: https://www.postgresql.org/docs/current/runtime-config-connection.html?utm_source=chatgpt.com "Documentation: 18: 19.3. Connections and Authentication"
[4]: https://clickhouse.com/docs/integrations/python?utm_source=chatgpt.com "Python integration with ClickHouse Connect"
# 0. Final target architecture

```text
Client / App
  ↓
https://nsfw-model.ansuman.yral.com
  ↓
Cloudflare Tunnel
  ↓
FastAPI Gateway
  - OpenAI-compatible API surface
  - API key auth
  - rate limits
  - quota checks
  - request validation
  - request metadata
  - streaming proxy
  - usage accounting
  - event emission
  ↓
vLLM Inference Server
  - model runtime
  - tensor parallel across 4 GPUs
  - continuous batching
  - KV-cache management
  - scheduler
  - Prometheus metrics
  ↓
4 GPUs on Vast AI host
```

Side systems:

```text
Postgres
  - transactional source of truth

Redis
  - fast counters, rate limits, queues, locks

ClickHouse
  - append-only analytics events

Prometheus + Grafana
  - live metrics and dashboards

NVIDIA DCGM Exporter
  - GPU telemetry
```

For this use case, **vLLM should be the main inference engine**, not Ollama. vLLM provides OpenAI-compatible serving, and exposes engine/scheduler configuration such as tensor parallelism, max batched tokens, and max active sequences. ([[vLLM](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/?utm_source=chatgpt.com)][1])

Ollama can stay as a local/dev tool, but not as the main production runtime.

---

# 1. Core design decisions

## 1.1 Inference engine

Use:

```text
vLLM
```

Initial mode:

```text
one model
one vLLM process
tensor_parallel_size = 4
one logical worker using all 4 GPUs
```

This means the 4 GPUs are not treated as four separate request workers.

Not this:

```text
GPU 1 → request A
GPU 2 → request B
GPU 3 → request C
GPU 4 → request D
```

But this:

```text
Request A
Request B
Request C
  ↓
vLLM batches/schedules them
  ↓
model execution happens across all 4 GPUs together
```

vLLM owns:

```text
model execution
continuous batching
KV-cache management
prefill/decode scheduling
token generation
```

Your FastAPI gateway owns:

```text
auth
quota
rate limits
request validation
metadata
usage accounting
stream proxying
batch job API
event logging
```

---

## 1.2 Public endpoint

Your public endpoint:

```text
https://nsfw-model.ansuman.yral.com
```

should point to Cloudflare Tunnel.

Cloudflare Tunnel should forward traffic to the local FastAPI gateway, not directly to vLLM.

Good:

```text
Cloudflare Tunnel → FastAPI Gateway → vLLM
```

Avoid:

```text
Cloudflare Tunnel → vLLM directly
```

Reason: vLLM should not be responsible for product-level auth, billing, token quota, per-user limits, batch job handling, or custom metadata.

---

## 1.3 API style

Expose an OpenAI-compatible API shape:

```text
GET  /v1/models
POST /v1/chat/completions
POST /v1/completions
POST /v1/embeddings       optional later
POST /v1/batch/jobs       for offline jobs
GET  /v1/batch/jobs/{id}
POST /v1/batch/jobs/{id}/cancel
GET  /health
GET  /metrics             protected/internal
```

For normal users, the main route is:

```text
POST /v1/chat/completions
```

The payload should look OpenAI-compatible so existing SDK clients can call your endpoint by changing:

```text
base_url
api_key
model
```

---

# 2. Service components to build

## 2.1 Cloudflare Tunnel layer

Responsibility:

```text
domain → secure tunnel → Vast host
```

This layer handles:

```text
DNS
TLS from client side
public ingress
basic Cloudflare protection
routing to local gateway
```

Important streaming note: for SSE streaming through Cloudflare Tunnel, the origin must send:

```http
Content-Type: text/event-stream
```

Cloudflare’s Tunnel docs say proxied traffic is buffered by default unless the origin includes `Content-Type: text/event-stream`, which tells `cloudflared` to stream data as it arrives instead of buffering the entire response. ([[Cloudflare Docs](https://developers.cloudflare.com/tunnel/troubleshooting/?utm_source=chatgpt.com)][2])

So your streaming endpoint must send proper SSE headers.

---

## 2.2 FastAPI gateway

This is the main product/backend layer.

Responsibilities:

```text
API key auth
request validation
rate limiting
quota management
routing to vLLM
SSE proxying
usage tracking
metadata enrichment
batch job API
admin/internal APIs
event emission
ClickHouse analytics buffer
```

This is the most important layer you will write yourself.

Boundary:

```text
FastAPI = product logic
vLLM = inference execution
```

---

## 2.3 vLLM server

Responsibility:

```text
model loading
GPU execution
continuous batching
KV-cache management
token generation
streaming tokens
inference metrics
```

Run vLLM on a private local port:

```text
127.0.0.1:8001
```

FastAPI runs on:

```text
127.0.0.1:8000
```

Cloudflare Tunnel forwards to:

```text
http://127.0.0.1:8000
```

Do not expose vLLM publicly.

---

## 2.4 Redis

Use Redis for fast mutable state:

```text
rate limits
concurrent request counters
token-per-minute counters
offline job queue
temporary quota reservations
stream heartbeat state
batch worker coordination
overload flags
```

Example Redis keys:

```text
rl:api_key:{api_key_id}:rpm
rl:api_key:{api_key_id}:tpm
concurrent:api_key:{api_key_id}
quota:project:{project_id}:daily_tokens
batch_queue:pending
request:{request_id}:state
analytics:spool_queue
```

Redis is not the durable source of truth. It is for speed and coordination.

---

## 2.5 Postgres + ClickHouse storage split

This is the corrected design.

Use:

```text
Postgres   → transactional source of truth
Redis      → live counters / queues / locks
ClickHouse → append-only analytics events
```

Do **not** use [ClickHouse](https://clickhouse.com/) as the transactional DB.

ClickHouse is a column-oriented OLAP database built for analytics, observability, and large-scale analytical queries, not for frequently updated transactional state. ([ClickHouse][3])

---

## 2.5.1 Postgres responsibility

Postgres owns correctness.

Use Postgres for:

```text
users
projects
api_keys
quota policies
billing plans
batch_jobs
webhook configs
model access policies
critical request state
critical usage records if needed
```

Postgres tables:

```text
users
projects
api_keys
quota_policies
batch_jobs
webhook_configs
request_audit_records
```

Postgres answers:

```text
Is this API key valid?
Which project owns this request?
Which model can this key access?
What is the user's quota policy?
What is the current batch job status?
Where should the webhook be sent?
```

---

## 2.5.2 Redis responsibility

Redis owns fast runtime state.

Use Redis for:

```text
RPM counters
TPM counters
active stream counters
concurrent request counters
temporary quota reservations
batch queue
worker coordination
distributed locks
overload flags
```

Redis answers:

```text
Is this key over RPM right now?
Is this project over TPM right now?
How many active requests does this key have?
Can we accept this request immediately?
Should offline workers pause?
```

---

## 2.5.3 ClickHouse responsibility

ClickHouse owns analytics history.

Use ClickHouse for:

```text
append-only request events
usage events
latency events
token usage analytics
stream lifecycle events
gateway error events
model runtime events
batch job analytics
dashboard queries
```

ClickHouse answers:

```text
How many tokens did this project use today?
What is p95 TTFT by model?
Which API keys are generating most traffic?
How many requests failed by error code?
What is request volume per hour?
How many client disconnects happened?
```

ClickHouse should not answer:

```text
Is this API key valid?
Can this user make a request now?
What is the current batch job status?
Should we allow this request?
```

Those belong to Postgres/Redis.

---

## 2.5.4 Analytics ingestion architecture

Do not insert into ClickHouse synchronously on every request.

Bad:

```text
request finishes
  ↓
INSERT one row into ClickHouse
  ↓
return response
```

Good:

```text
request finishes
  ↓
emit event into local queue
  ↓
return response
  ↓
background flusher batches events
  ↓
bulk insert into ClickHouse
```

Final analytics path:

```text
FastAPI Gateway
  ↓
Event Collector
  ↓
Bounded in-memory queue
  ↓
Optional Redis/local disk spool for critical events
  ↓
Background batch flusher
  ↓
[ClickHouse](https://clickhouse.com/docs/optimize/asynchronous-inserts) Distributed table
  ↓
ReplicatedMergeTree local tables
```

ClickHouse recommends avoiding many small synchronous inserts because they create too many parts and hurt query performance. Its async insert docs explain that async inserts buffer data and flush based on data size, time, or query-count thresholds. ([ClickHouse][4])

---

## 2.5.5 Event reliability classes

Split events into two classes.

### Critical events

These must not be lost:

```text
usage_events
request_completed
client_disconnected with generated token count
batch_job_completed
billing-relevant events
```

For critical events:

```text
write to Postgres or durable local spool first
then mirror to ClickHouse asynchronously
```

### Non-critical events

These can be dropped under pressure:

```text
debug lifecycle events
verbose internal traces
per-token debug events
temporary scheduler snapshots
```

For non-critical events:

```text
bounded memory queue is enough
drop if queue is full
increment dropped_events counter
```

Rule:

```text
ClickHouse failure should not break online inference.
Critical usage/billing events must be recoverable.
```

---

## 2.5.6 ClickHouse batch flush policy

Start with:

```text
in-memory queue max size: 50,000 events
target flush size: 5,000–10,000 rows
min flush size: 1,000 rows
max flush size: 50,000 rows
flush interval: 1–5 seconds
max retry attempts: 5
retry policy: exponential backoff
```

Flush when any condition is met:

```text
batch has enough rows
or flush interval elapsed
or batch byte size threshold reached
or graceful shutdown started
```

Use [ClickHouse](https://clickhouse.com/docs/best-practices/selecting-an-insert-strategy) async insert as an additional safety/performance layer:

```sql
SET async_insert = 1;
SET wait_for_async_insert = 1;
```

ClickHouse recommends `async_insert=1, wait_for_async_insert=1` for production reliability because the insert is acknowledged only after data is flushed successfully; `wait_for_async_insert=0` is fire-and-forget and can hide failures. ([ClickHouse][5])

---

## 2.5.7 ClickHouse failure behavior

If ClickHouse is down:

```text
do not fail inference requests
pause flush attempts
retry with exponential backoff
keep critical events in Postgres/local spool
drop non-critical events after queue limit
emit alert
```

If ClickHouse is slow:

```text
increase batch size up to max
reduce flush frequency
apply backpressure only to analytics pipeline
never block token streaming
```

If local queue is full:

```text
critical event → Postgres/local disk spool fallback
non-critical event → drop and increment dropped_events counter
```

Analytics pipeline metrics:

```text
analytics_queue_size
analytics_flush_batch_size
analytics_flush_duration_ms
analytics_flush_failed_total
analytics_events_dropped_total
analytics_events_spooled_total
clickhouse_insert_latency_ms
clickhouse_last_successful_flush_timestamp
```

---

## 2.5.8 ClickHouse table model

Use a cluster-safe pattern:

```text
local table      → ReplicatedMergeTree
distributed table → Distributed
```

Example database:

```sql
CREATE DATABASE IF NOT EXISTS inference_analytics ON CLUSTER yral_cluster;
```

Main usage table:

```sql
CREATE TABLE IF NOT EXISTS inference_analytics.usage_events_local
ON CLUSTER yral_cluster
(
    event_date Date DEFAULT toDate(completed_at),
    completed_at DateTime64(3, 'UTC'),

    request_id String,
    user_id String,
    project_id String,
    api_key_id String,

    model LowCardinality(String),
    request_type LowCardinality(String), -- online, batch
    endpoint LowCardinality(String),

    stream UInt8,

    prompt_tokens UInt32,
    completion_tokens UInt32,
    total_tokens UInt32,
    reserved_tokens UInt32,

    status LowCardinality(String),
    finish_reason LowCardinality(String),
    error_code LowCardinality(String),
    client_disconnected UInt8,

    queue_ms UInt32,
    ttft_ms UInt32,
    decode_ms UInt32,
    total_ms UInt32,

    cost_estimate Float64,

    ip_hash String,
    user_agent_hash String,

    metadata_json String
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{shard}/inference_analytics/usage_events_local',
    '{replica}'
)
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, project_id, api_key_id, model, completed_at, request_id)
TTL event_date + INTERVAL 365 DAY
SETTINGS index_granularity = 8192;
```

Distributed table:

```sql
CREATE TABLE IF NOT EXISTS inference_analytics.usage_events
ON CLUSTER yral_cluster
AS inference_analytics.usage_events_local
ENGINE = Distributed(
    yral_cluster,
    inference_analytics,
    usage_events_local,
    cityHash64(project_id, request_id)
);
```

Lifecycle/internal event table:

```sql
CREATE TABLE IF NOT EXISTS inference_analytics.inference_events_local
ON CLUSTER yral_cluster
(
    event_date Date DEFAULT toDate(event_time),
    event_time DateTime64(3, 'UTC'),

    event_id UUID,
    request_id String,

    event_type LowCardinality(String),
    request_type LowCardinality(String),
    endpoint LowCardinality(String),
    method LowCardinality(String),

    user_id String,
    project_id String,
    api_key_id String,

    model LowCardinality(String),
    model_version LowCardinality(String),

    stream UInt8,
    status LowCardinality(String),
    finish_reason LowCardinality(String),
    error_code LowCardinality(String),

    prompt_tokens UInt32,
    completion_tokens UInt32,
    total_tokens UInt32,
    estimated_tokens UInt32,

    queue_ms UInt32,
    ttft_ms UInt32,
    decode_ms UInt32,
    total_ms UInt32,

    batch_size UInt32,
    vllm_running_requests UInt32,
    vllm_waiting_requests UInt32,

    gpu_count UInt8,
    gpu_memory_used_mb UInt32,
    kv_cache_usage Float32,

    client_disconnected UInt8,

    ip_hash String,
    user_agent_hash String,

    metadata_json String
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{shard}/inference_analytics/inference_events_local',
    '{replica}'
)
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, project_id, model, event_type, event_time, request_id)
TTL event_date + INTERVAL 180 DAY
SETTINGS index_granularity = 8192;
```

Distributed table:

```sql
CREATE TABLE IF NOT EXISTS inference_analytics.inference_events
ON CLUSTER yral_cluster
AS inference_analytics.inference_events_local
ENGINE = Distributed(
    yral_cluster,
    inference_analytics,
    inference_events_local,
    cityHash64(project_id, request_id)
);
```

---

## 2.6 Prometheus + Grafana

Use this for live metrics.

[vLLM](https://docs.vllm.ai/en/stable/design/metrics.html) exposes Prometheus-compatible metrics and has observability support around server/request metrics. ([vLLM][6])

Collect:

```text
FastAPI metrics
vLLM metrics
GPU metrics
host metrics
Redis metrics
ClickHouse ingestion metrics
Cloudflare/tunnel health if possible
```

Prometheus is for live operational metrics.

ClickHouse is for historical analytics.

---

## 2.7 NVIDIA DCGM Exporter

Use NVIDIA DCGM Exporter for GPU metrics.

NVIDIA DCGM Exporter exposes GPU telemetry for Prometheus scraping. ([[NVIDIA Docs](https://docs.nvidia.com/datacenter/dcgm/latest/gpu-telemetry/dcgm-exporter.html)][7])

Track:

```text
GPU utilization
GPU memory used
GPU temperature
GPU power draw
GPU errors
SM utilization
memory bandwidth
```
Yes. Preserve the design exactly. Just add **Sentry as an application/runtime error observability layer**, not as a GPU telemetry replacement.

Add this section after:

**2.7 NVIDIA DCGM Exporter**

Your existing plan already keeps GPU telemetry under DCGM Exporter + Prometheus/Grafana, which is the right boundary. Sentry should sit beside that as the app-debugging layer. 

---

# 2.8 Sentry

Use the existing self-hosted Sentry cluster for application-level error monitoring, tracing, and debugging.

Sentry should not replace Prometheus, Grafana, vLLM metrics, or NVIDIA DCGM Exporter.

Sentry is responsible for:

* application exceptions
* failed request lifecycle bugs
* FastAPI gateway crashes
* batch worker crashes
* ClickHouse flusher failures
* Redis/Postgres connection errors
* quota/accounting bugs
* client disconnect cleanup bugs
* upstream vLLM timeout errors
* malformed upstream responses
* deployment/release regressions
* request-level tracing across internal services

Sentry should be integrated into:

* FastAPI Gateway
* batch worker process
* analytics/event flusher
* background spool recovery process
* webhook delivery worker if added later
* internal admin APIs
* any custom wrapper/client code that talks to vLLM

Sentry should not be used for:

* GPU utilization monitoring
* GPU memory dashboards
* GPU temperature tracking
* GPU power draw tracking
* KV-cache dashboards
* vLLM running/waiting request dashboards
* high-frequency time-series metrics
* business usage analytics
* billing source of truth
* ClickHouse replacement
* Prometheus replacement

Those remain owned by:

* NVIDIA DCGM Exporter
* vLLM Prometheus metrics
* Prometheus
* Grafana
* ClickHouse

Sentry events should include enough context to debug one failed request without storing sensitive payloads.

Recommended Sentry context/tags:

* request_id
* user_id
* project_id
* api_key_id
* model
* endpoint
* request_type
* stream true/false
* batch_job_id if applicable
* upstream_status_code
* error_code
* client_disconnected true/false
* deployment_version
* host_id

Do not send to Sentry:

* raw API keys
* authorization headers
* full prompts by default
* full user payloads
* secrets
* raw webhook credentials
* database credentials
* Cloudflare tunnel tokens

Sentry should capture:

* unhandled exceptions
* handled exceptions that represent system failure
* failed background jobs
* failed ClickHouse flushes after retry threshold
* repeated Redis/Postgres connection failures
* upstream vLLM request failures
* unexpected response parsing failures
* request finalization failures
* quota finalization failures
* webhook delivery failures

Sentry should not capture every normal user error.

Do not send routine events like:

* normal 400 validation errors
* expected 401 invalid API key responses
* expected 429 rate limit responses
* expected 413 payload too large responses
* normal client disconnects unless they reveal cleanup bugs
* every successful request

For tracing, Sentry should be used to understand request flow across the product layer:

* request enters FastAPI
* auth check
* quota/rate-limit check
* forward to vLLM
* first token received
* stream completed or failed
* usage finalized
* event queued for ClickHouse

Sentry tracing should be sampled.

Do not trace every request at full volume in production.

Use higher sampling for:

* errors
* slow requests
* batch jobs
* admin/internal operations
* ClickHouse flusher failures
* early-stage testing

Use lower sampling for:

* normal successful online inference requests
* high-volume streaming traffic

Operational rule:

Sentry answers:

Why did this request, worker, or code path fail?

Prometheus/Grafana answers:

Is the service healthy right now?

DCGM Exporter answers:

Are the GPUs healthy?

vLLM metrics answer:

Is the inference engine overloaded?

ClickHouse answers:

What happened historically across users, projects, models, and time?

Sentry failure should not break inference.

If Sentry is down or unreachable:

* online requests must continue
* batch jobs must continue
* ClickHouse flushing must continue
* logs should still be written locally
* Sentry SDK should fail silently or degrade safely

---

# 3. Request lifecycle to implement

## 3.1 Online request flow

```text
1. Client calls POST /v1/chat/completions

2. Cloudflare Tunnel forwards request to FastAPI

3. FastAPI creates request_id

4. FastAPI validates JSON payload

5. FastAPI validates API key using Postgres

6. FastAPI resolves:
   - api_key_id
   - user_id
   - project_id
   - allowed models
   - quota policy

7. FastAPI checks Redis:
   - RPM
   - TPM
   - concurrent request limit
   - daily temporary counters
   - overload flag

8. FastAPI checks request limits:
   - max input tokens
   - max output tokens
   - max body size
   - model access

9. FastAPI estimates prompt tokens

10. FastAPI reserves temporary quota in Redis

11. FastAPI emits request_received/request_accepted event

12. FastAPI forwards request to vLLM

13. vLLM queues/schedules/batches internally

14. vLLM starts returning tokens

15. FastAPI proxies tokens to client over SSE

16. FastAPI tracks:
   - TTFT
   - generated tokens
   - disconnects
   - errors
   - finish reason

17. FastAPI finalizes quota and usage

18. Critical usage record is written to Postgres or durable spool if needed

19. Analytics event is queued for ClickHouse batch flush

20. Response completes
```

---

# 4. Auth plan

## 4.1 API key format

Use keys like:

```text
sk_yral_xxxxxxxxxxxxxxxxx
```

Store only the hash.

Postgres table:

```text
api_keys
--------
id
key_hash
prefix
user_id
project_id
name
status
created_at
last_used_at
expires_at
allowed_models
rpm_limit
tpm_limit
daily_token_limit
monthly_token_limit
max_concurrent_requests
```

Never store raw API keys.

Only show the raw key once at creation time.

---

## 4.2 Auth middleware

Every protected request uses:

```http
Authorization: Bearer sk_...
```

Middleware:

```text
extract key
hash key
lookup api_key in Postgres
check active status
check expiry
attach auth context to request
```

Request context:

```text
request.state.api_key_id
request.state.user_id
request.state.project_id
request.state.allowed_models
request.state.rate_limit_policy
```

Cloudflare protects the public door.

FastAPI decides who can spend GPU.

---

# 5. Rate limiting and quota plan

## 5.1 Requests per minute

Protects API spam.

```text
100 requests / minute / API key
```

Redis key:

```text
rl:api_key:{id}:rpm
```

---

## 5.2 Tokens per minute

Protects GPU usage better than request count.

```text
20,000 tokens / minute / API key
```

Redis key:

```text
rl:api_key:{id}:tpm
```

This should count:

```text
estimated prompt tokens before request
actual completion tokens during/after generation
```

---

## 5.3 Concurrent requests

Very important for streaming.

Example:

```text
max 3 active streaming requests per API key
```

Redis key:

```text
concurrent:api_key:{id}
```

Increment when request starts.

Decrement when request completes, errors, or disconnects.

Use `try/finally` style cleanup so counters do not leak.

---

## 5.4 Daily/monthly quota

For billing and abuse control.

Example:

```text
1M tokens/day
10M tokens/month
```

Use:

```text
Redis    → fast daily/monthly counters
Postgres → source-of-truth plan/quota config
ClickHouse → analytical token history
```

Periodically reconcile Redis/Postgres counters with ClickHouse or usage events.

---

## 5.5 Request size limits

Reject bad requests early.

Limits:

```text
max input tokens
max output tokens
max total tokens
max request body size
max messages count
max images/files if multimodal later
```

Example:

```text
max_input_tokens = 8192
max_output_tokens = 2048
max_total_tokens = 10000
```

For batch jobs, limits can be higher.

---

# 6. Queue plan

You need **two queue systems**, not one.

---

## 6.1 Online queue

For online requests, do not build your own heavy GPU queue first.

Use:

```text
vLLM internal scheduler and batching
```

Your FastAPI layer should only have admission control.

It decides:

```text
accept request
reject with 429
reject with 503
wait very briefly
forward to vLLM
```

Do not put online requests into Celery and make users wait behind a durable worker queue.

Online request policy:

```text
small queue
strict timeout
fail fast under overload
interactive priority
```

---

## 6.2 Offline queue

For jobs that can complete later:

```text
POST /v1/batch/jobs
```

Use a durable queue.

Options:

```text
Redis Streams
Postgres jobs table
Celery/RQ/Dramatiq
```

For your setup, start simple:

```text
Postgres batch_jobs table + Redis queue
```

Flow:

```text
1. Client submits batch job
2. API writes batch_jobs row in Postgres
3. API returns job_id
4. Worker pulls job from Redis/Postgres
5. Worker checks online load
6. Worker sends request to vLLM only if capacity is available
7. Result is stored in Postgres
8. Analytics event is emitted to ClickHouse buffer
9. Client polls result or receives webhook later
```

---

## 6.3 Queue split

Do not split queues by prompt length in v1.

Do this:

```text
interactive_queue
batch_queue
admin_internal_queue
```

Split by **priority/SLO**, not by token length.

Later, after metrics, you can add:

```text
short_interactive
long_interactive
large_context_batch
```

But not in v1.

---

# 7. Scheduling and batching plan

## 7.1 What your app scheduler should do

Your app-level scheduler decides:

```text
who is allowed
who gets rejected
who gets priority
which model to use
whether request is online or batch
how much quota to reserve
whether offline worker should run
```

Your app should not decide CUDA-level batching.

---

## 7.2 What [vLLM](https://docs.vllm.ai/en/stable/configuration/engine_args.html) scheduler should do

vLLM decides:

```text
which requests enter the active batch
how many sequences run in one iteration
how many tokens are processed per iteration
how KV cache is allocated
how prefill/decode is interleaved
how continuous batching happens
```

vLLM exposes controls like:

```text
max_model_len
gpu_memory_utilization
max_num_seqs
max_num_batched_tokens
max_num_partial_prefills
max_long_partial_prefills
long_prefill_token_threshold
```

These are runtime/scheduler capacity knobs, not product-level API controls. ([vLLM][8])

---

## 7.3 Batching model

Batching is **not semantic**.

Do not batch like:

```text
NSFW prompts together
coding prompts together
chat prompts together
```

Batching is based on execution shape:

```text
prompt tokens
decode tokens
active sequences
KV cache availability
GPU memory
max_num_batched_tokens
max_num_seqs
```

Two unrelated prompts can be in the same batch.

That is normal.

---

# 8. Capacity and max batch finding plan

You will not know the max batch size upfront.

You must benchmark.

## 8.1 Define traffic profiles

```text
Profile A: short prompt, short output
- 200 input tokens
- 100 output tokens

Profile B: medium prompt, medium output
- 1000 input tokens
- 500 output tokens

Profile C: long prompt, short output
- 8000 input tokens
- 200 output tokens

Profile D: short prompt, long output
- 500 input tokens
- 4000 output tokens

Profile E: worst case
- max allowed input
- max allowed output
```

---

## 8.2 Benchmark gradually

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

For each level record:

```text
requests/sec
tokens/sec
TTFT p50/p95/p99
TPOT p50/p95/p99
end-to-end latency p50/p95/p99
GPU memory usage
KV-cache usage
OOMs
client disconnects
503s
429s
vLLM running requests
vLLM waiting requests
ClickHouse event queue lag
analytics flush latency
```

---

## 8.3 Tune vLLM

Tune:

```text
max_model_len
gpu_memory_utilization
max_num_seqs
max_num_batched_tokens
max_num_partial_prefills
max_long_partial_prefills
long_prefill_token_threshold
```

Capacity target should not be:

```text
maximum requests before OOM
```

It should be:

```text
maximum active load before p95 latency becomes unacceptable
```

That is your real production limit.

---

# 9. Streaming plan

## 9.1 Use SSE for live token streaming

For OpenAI-compatible streaming, use:

```text
Server-Sent Events
```

Response headers:

```http
Content-Type: text/event-stream
Cache-Control: no-cache, no-transform
Connection: keep-alive
X-Accel-Buffering: no
```

Cloudflare Tunnel needs `Content-Type: text/event-stream` to avoid buffering live stream responses. ([[Cloudflare Docs](https://developers.cloudflare.com/tunnel/troubleshooting/?utm_source=chatgpt.com)][2])

---

## 9.2 Streaming flow

```text
client connects
  ↓
FastAPI forwards request to vLLM with stream=true
  ↓
vLLM returns token chunks
  ↓
FastAPI forwards each chunk immediately
  ↓
FastAPI tracks tokens and timing
  ↓
final chunk is sent
  ↓
usage is finalized
  ↓
ClickHouse analytics event is queued
```

---

## 9.3 Long responses

For 10k-token responses:

```text
send heartbeat events
track generated tokens continuously
set max output token limits
detect client disconnects
cancel upstream generation if client disconnects
store partial usage
emit client_disconnected event if needed
```

Heartbeat example:

```text
: keepalive
```

This keeps the connection active if there is a long gap before the first generated token.

---

## 9.4 If the request terminates midway

If the client disconnects:

```text
1. FastAPI detects disconnect
2. FastAPI cancels upstream vLLM request if possible
3. request status = client_disconnected
4. generated token count so far is recorded
5. concurrent counter is decremented
6. quota is finalized based on actual usage
7. critical usage event is saved/recoverable
8. ClickHouse analytics event is queued
```

Do not continue generating tokens after the client is gone.

That wastes GPU.

---

# 10. Offline/batch job plan

## 10.1 Batch endpoint

Add:

```text
POST /v1/batch/jobs
GET  /v1/batch/jobs/{job_id}
POST /v1/batch/jobs/{job_id}/cancel
```

Initial submit response:

```json
{
  "job_id": "job_abc123",
  "status": "queued"
}
```

---

## 10.2 Batch job table

Postgres table:

```text
batch_jobs
----------
id
user_id
project_id
api_key_id
model
input_payload
status
priority
estimated_prompt_tokens
max_completion_tokens
actual_prompt_tokens
actual_completion_tokens
result_payload
error_code
error_message
created_at
started_at
completed_at
deadline_at
```

Statuses:

```text
queued
running
succeeded
failed
cancelled
expired
```

ClickHouse receives only append-only analytics events about the batch job lifecycle.

---

## 10.3 Batch worker policy

Batch workers should respect online load.

Before sending work to vLLM, check:

```text
online queue depth
vLLM running requests
vLLM waiting requests
GPU memory usage
KV-cache usage
current TTFT p95
Redis overload flag
```

If online load is high:

```text
batch worker waits
```

If online load is low:

```text
batch worker sends jobs
```

This keeps user-facing traffic fast.

---

## 10.4 Webhooks

Use webhooks only for async jobs.

Not for token streaming.

Batch job webhook event:

```json
{
  "event": "batch_job.completed",
  "job_id": "job_abc123",
  "status": "succeeded"
}
```

Webhook config and delivery status belong in Postgres.

Webhook delivery analytics can be mirrored to ClickHouse.

---

# 11. Response metadata plan

## 11.1 Non-streaming response

Return OpenAI-compatible shape:

```json
{
  "id": "chatcmpl_req_123",
  "object": "chat.completion",
  "created": 1760000000,
  "model": "gemma-31b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 1200,
    "completion_tokens": 800,
    "total_tokens": 2000
  }
}
```

Some OpenAI SDK clients may not expect custom top-level fields.

Safer approach:

```text
OpenAI-compatible body
extra metadata in response headers
full metadata stored internally
```

Headers:

```http
x-request-id: req_123
x-queue-ms: 41
x-ttft-ms: 620
x-total-ms: 9210
x-model-worker: vllm-0
```

---

## 11.2 Streaming response

For streaming, send normal SSE chunks.

At the end:

```text
data: [DONE]
```

Internally store full usage even if the client ignores final metadata.

If you control the client, you can send a final usage chunk before `[DONE]`.

---

# 12. Token accounting and storage plan

## 12.1 Token usage lifecycle

```text
1. Request comes in
2. Estimate prompt tokens before forwarding
3. Reserve quota in Redis
4. Generate response
5. Count completion tokens
6. Finalize usage
7. Update Redis counters
8. Write critical usage record to Postgres if billing-critical
9. Emit usage event to ClickHouse event buffer
10. Background flusher writes batched events to ClickHouse
```

---

## 12.2 Postgres usage state

Postgres should store correctness-critical records.

Example:

```text
request_audit_records
---------------------
id
request_id
user_id
project_id
api_key_id
model
status
prompt_tokens
completion_tokens
total_tokens
created_at
completed_at
```

You do not need to put every debug lifecycle event in Postgres.

Postgres should store only what you need for correctness, support, billing, and recovery.

---

## 12.3 ClickHouse usage events

ClickHouse stores analytical usage history.

ClickHouse table:

```text
usage_events
------------
request_id
user_id
project_id
api_key_id
model
request_type
endpoint
stream
prompt_tokens
completion_tokens
total_tokens
reserved_tokens
status
finish_reason
error_code
client_disconnected
queue_ms
ttft_ms
decode_ms
total_ms
cost_estimate
completed_at
metadata_json
```

Statuses:

```text
succeeded
failed
cancelled
client_disconnected
rate_limited
rejected
```

This table is append-only.

Do not update rows in ClickHouse for normal request state changes.

---

## 12.4 ClickHouse inference events

For lifecycle/debug analytics:

```text
inference_events
----------------
event_id
request_id
event_type
event_time
user_id
project_id
api_key_id
model
status
error_code
metadata_json
```

Example event types:

```text
request_received
auth_passed
rate_limit_passed
quota_reserved
forwarded_to_vllm
first_token_received
stream_completed
usage_recorded
request_failed
client_disconnected
batch_job_queued
batch_job_started
batch_job_completed
```

---

## 12.5 Privacy and logging safety

Do not store full prompts by default.

Store:

```text
prompt hash
token count
model
latency
status
error code
truncated debug sample only if explicitly enabled
```

Avoid storing:

```text
raw API keys
authorization headers
full user prompts by default
sensitive request payloads
```

---

# 13. Internal logging plan

You need logs at multiple layers.

## 13.1 Gateway logs

Log every request state transition:

```text
request_received
auth_passed
rate_limit_passed
quota_reserved
forwarded_to_vllm
first_token_received
stream_completed
usage_recorded
request_failed
client_disconnected
analytics_event_queued
analytics_flush_failed
```

Each log line should include:

```text
request_id
api_key_id
user_id
project_id
model
event
timestamp
duration_ms
```

---

## 13.2 vLLM logs

Collect vLLM process logs.

Important things to watch:

```text
model loaded
GPU memory allocation
number of running requests
number of waiting requests
KV-cache usage
prompt tokens/sec
generation tokens/sec
preemption
OOM
worker crash
```

---

## 13.3 GPU logs

Collect:

```text
GPU utilization
VRAM usage
temperature
power draw
ECC/errors if available
driver errors
CUDA errors
```

Use DCGM Exporter for this. ([[NVIDIA Docs](https://docs.nvidia.com/datacenter/dcgm/latest/gpu-telemetry/dcgm-exporter.html)][7])

---

## 13.4 ClickHouse ingestion logs

Log analytics ingestion health:

```text
event_enqueued
event_dropped
event_spooled
flush_started
flush_succeeded
flush_failed
flush_retried
clickhouse_unavailable
```

Metrics:

```text
analytics_queue_size
analytics_flush_batch_size
analytics_flush_duration_ms
analytics_flush_failed_total
analytics_events_dropped_total
analytics_events_spooled_total
clickhouse_insert_latency_ms
clickhouse_last_successful_flush_timestamp
```

---

# 14. Metrics and dashboards

## 14.1 Gateway dashboard

Show:

```text
requests/sec
success rate
error rate
429 rate
503 rate
p50/p95/p99 total latency
p50/p95/p99 TTFT
client disconnects
active streams
tokens/minute
top API keys by usage
analytics queue size
ClickHouse flush failures
```

---

## 14.2 vLLM dashboard

Show:

```text
running requests
waiting requests
KV-cache usage %
prompt tokens/sec
generation tokens/sec
TTFT
inter-token latency
end-to-end latency
request success by finish reason
```

[vLLM](https://docs.vllm.ai/en/stable/design/metrics.html) exposes Prometheus metrics for production observability. ([vLLM][6])

---

## 14.3 GPU dashboard

Show:

```text
GPU utilization per GPU
GPU memory used per GPU
GPU temperature
GPU power usage
GPU errors
memory bandwidth
```

---

## 14.4 Business dashboard

Backed mostly by ClickHouse:

```text
tokens by user
tokens by project
tokens by API key
requests by model
daily/monthly usage
failed requests
batch jobs completed
batch jobs pending
client disconnects by model
p95 latency by model/project
cost estimate by project
```

---

# 15. Error handling plan

Standard error responses:

```text
400 bad_request
401 invalid_api_key
403 model_not_allowed
408 request_timeout
413 payload_too_large
429 rate_limit_exceeded
499 client_disconnected
500 internal_error
502 upstream_error
503 server_overloaded
504 upstream_timeout
```

For overload:

```json
{
  "error": {
    "message": "Server is overloaded. Please retry later.",
    "type": "server_overloaded",
    "code": "server_overloaded"
  }
}
```

Do not let requests hang forever.

ClickHouse insert failure should not become user-facing `500`.

---

# 16. Overload policy

When load is high:

```text
first: reject new batch jobs temporarily
second: pause offline workers
third: drop non-critical analytics events if queue is full
fourth: reject low-priority online requests
fifth: reject all new requests with 503
```

Never let the server OOM.

Use these signals:

```text
vLLM waiting requests too high
KV-cache usage too high
GPU memory too high
TTFT p95 too high
active streams too high
Redis concurrent counters too high
analytics queue too high
ClickHouse flush failures too high
```

---

# 17. Security plan

## 17.1 Network

```text
vLLM only bound to localhost
FastAPI only exposed through Cloudflare Tunnel
admin routes protected
metrics endpoint private
Redis/Postgres/ClickHouse not public
```

---

## 17.2 API keys

```text
hash keys
prefix lookup
rotation support
revocation support
last used tracking
per-key limits
per-key model access
```

---

## 17.3 Request body protection

Add:

```text
max body size
max messages count
max token count
timeout
JSON schema validation
```

---

## 17.4 Logging safety

Avoid logging:

```text
raw API keys
full user prompts by default
authorization headers
sensitive request payloads
```

Log:

```text
request_id
api_key_id
token counts
latency
status
model
hashes/truncated samples if needed
```

---

# 18. Deployment plan

## Phase 1: Basic serving

Goal: get the model serving behind the domain.

Build:

```text
Cloudflare Tunnel
FastAPI gateway
vLLM server
/v1/models
/v1/chat/completions
basic non-streaming request
basic streaming request
```

Success criteria:

```text
OpenAI client can call your endpoint
streaming works through Cloudflare Tunnel
vLLM is not publicly exposed
```

---

## Phase 2: Auth and rate limits

Build:

```text
Postgres api_keys table
API key creation script
auth middleware
Redis RPM limit
Redis concurrent request limit
basic TPM estimate
```

Success criteria:

```text
invalid key gets 401
over-limit key gets 429
valid key can stream response
concurrent request limit works
```

---

## Phase 3: Token accounting and metadata

Build:

```text
Postgres request_audit_records table
Redis quota reservation/finalization
prompt token estimation
completion token counting
response usage field
x-request-id headers
streaming finalization logic
disconnect accounting
```

Success criteria:

```text
every request has request_id
every completed/failed/disconnected request has usage accounting
token totals are visible per API key/user/project
client disconnects do not leak counters
```

---

## Phase 4: ClickHouse analytics ingestion

Build:

```text
ClickHouse inference_analytics database
usage_events_local ReplicatedMergeTree table
usage_events Distributed table
inference_events_local ReplicatedMergeTree table
inference_events Distributed table
FastAPI event collector
bounded in-memory queue
background batch flusher
retry/backoff logic
drop/spool policy
analytics ingestion metrics
```

Success criteria:

```text
request path does not block on ClickHouse
events flush in batches
ClickHouse downtime does not break inference
critical usage events are recoverable
non-critical events can be dropped under pressure
business dashboard queries work from ClickHouse
```

---

## Phase 5: Offline jobs

Build:

```text
/v1/batch/jobs
/v1/batch/jobs/{id}
batch_jobs table in Postgres
Redis batch queue
worker process
low-priority execution policy
optional webhook later
ClickHouse batch job analytics events
```

Success criteria:

```text
batch job returns job_id
worker processes job
result is stored in Postgres
usage analytics goes to ClickHouse
online requests get priority
```

---

## Phase 6: Observability

Build:

```text
Prometheus
Grafana
vLLM metrics scrape
FastAPI metrics
DCGM Exporter
Node Exporter
Redis metrics
ClickHouse ingestion metrics
structured logs
request_id correlation
```

Success criteria:

```text
dashboard shows request latency
dashboard shows TTFT
dashboard shows GPU usage
dashboard shows KV-cache usage
dashboard shows tokens/sec
dashboard shows ClickHouse ingestion lag
logs can trace one request across gateway and vLLM
```

Add Sentry integration for:

* FastAPI Gateway
* batch workers
* analytics flusher
* webhook worker if added later
* request tracing
* exception capture
* release/deployment regression tracking

Success criteria:

* application exceptions appear in Sentry
* failed batch jobs appear in Sentry
* ClickHouse flusher failures appear in Sentry
* upstream vLLM timeout/parsing failures appear in Sentry
* every Sentry event has request_id where applicable
* no raw API keys or full prompts are sent to Sentry
* Sentry outage does not affect inference serving


---

## Phase 7: Capacity benchmarking

Build benchmark scripts for:

```text
short requests
medium requests
long prompt requests
long output requests
streaming requests
batch jobs
mixed traffic
ClickHouse analytics ingestion load
```

Tune:

```text
max_num_seqs
max_num_batched_tokens
max_model_len
gpu_memory_utilization
max output token limits
gateway concurrency limits
ClickHouse flush batch size
analytics queue size
offline worker concurrency
```

Success criteria:

```text
known safe concurrency
known p95 TTFT
known p95 total latency
known tokens/sec
known overload threshold
known analytics ingestion capacity
```

---

## Phase 8: Reliability hardening

Build:

```text
process supervisor
auto-restart
health checks
startup model warmup
graceful shutdown
log rotation
disk usage alerts
GPU memory alerts
Redis/Postgres backup if needed
ClickHouse flusher graceful drain
local spool recovery
```

Success criteria:

```text
server recovers from process crash
bad request does not crash service
client disconnect does not leak concurrency counter
batch worker does not overwhelm online traffic
ClickHouse outage does not break inference
analytics flusher drains safely on shutdown
```

---

# 19. Recommended first MVP scope

Do this first:

```text
Cloudflare Tunnel
FastAPI gateway
vLLM with tensor_parallel_size=4
Postgres API key/auth tables
Redis rate limiter
SSE streaming
token accounting
ClickHouse batched analytics ingestion
Prometheus + Grafana
DCGM Exporter
basic batch job endpoint
```

Do not do this in v1:

```text
custom GPU scheduler
semantic batching
multi-node cluster
complex priority algorithms
Kubernetes
TensorRT-LLM
advanced billing engine
multiple model routing
fine-grained queue classes by token length
ClickHouse as transactional DB
per-token analytics inserts
synchronous ClickHouse writes in request path
```

Those can come later.

---

# 20. Most important engineering rule

The clean boundary is:

```text
Cloudflare Tunnel owns public ingress.

FastAPI Gateway owns product logic:
  auth
  quota
  validation
  request lifecycle
  response metadata
  event emission

vLLM owns inference execution:
  model loading
  scheduling
  batching
  KV cache
  token generation

Redis owns fast runtime state:
  rate limits
  token counters
  concurrency
  queues
  locks

Postgres owns transactional correctness:
  users
  projects
  API keys
  quota policies
  batch job status
  webhook configs
  critical audit state

ClickHouse owns append-only analytics:
  usage events
  latency events
  request lifecycle events
  business dashboards
  historical token analytics

Prometheus/Grafana owns live monitoring:
  service health
  GPU health
  vLLM metrics
  ingestion lag


Add this near the end of the full report, after the Sentry section and before the deployment phases.

---

# 21. Implementation Ambiguity Guardrails

This section removes the remaining implementation ambiguity in the plan. The coding agent must follow these rules unless explicitly instructed otherwise.

## 21.1 Single-container networking rule

FastAPI Gateway, vLLM, and Cloudflare Tunnel will run inside the same Vast AI GPU container.

Because of this, localhost networking is valid inside the GPU container.

FastAPI may call vLLM through localhost.

Cloudflare Tunnel may forward public traffic to the local FastAPI Gateway inside the same container.

The coding agent should not introduce Docker Compose service-name networking, multi-container routing, Kubernetes networking, or cross-host vLLM routing in v1.

The GPU container is the inference runtime boundary.

## 21.2 External ClickHouse rule

ClickHouse already exists externally at:

`clickhouse.ansuman.yral.com`

The coding agent must not install, bootstrap, or manage a local ClickHouse server on the GPU container.

The GPU inference service should connect to the existing ClickHouse cluster using a dedicated ClickHouse user created for this service.

ClickHouse is only for append-only analytics and historical querying.

ClickHouse must not be used for API key validation, quota correctness, batch job state, billing source of truth, or request admission control.

## 21.3 External Postgres rule

Postgres already exists externally at:

`postgress.ansuman.yral.com`

The coding agent must not install or run Postgres on the GPU container.

The GPU inference service should connect to the existing Postgres server using a dedicated Postgres user created for this service.

Postgres is the transactional source of truth for correctness-critical data, including API keys, quota policy, batch job state, request audit records, and critical usage records.

## 21.4 External Prometheus/Grafana rule

Prometheus and Grafana will run on existing owned servers, such as `ansuman-1`, `ansuman-2`, or `ansuman-3`.

The GPU container should only expose private metrics endpoints.

Prometheus should scrape the GPU container over Tailscale or another private network.

The coding agent must not expose metrics endpoints publicly through Cloudflare Tunnel.

Cloudflare Tunnel should expose only the public inference API.

Metrics, admin routes, debug routes, vLLM ports, Redis, Postgres, ClickHouse, and internal worker endpoints must remain private.

## 21.5 Logs, metrics, and errors boundary

Do not mix logs, metrics, and errors into one system.

Prometheus is for metrics.

Grafana is for dashboards.

Sentry is for application errors, exceptions, traces, and release regressions.

ClickHouse is for historical analytics.

Raw application logs may stay local in v1 or be shipped later to a logging system such as Loki if required.

The coding agent should not try to send all raw logs to Prometheus.

## 21.6 Batch worker execution rule

Batch workers may bypass public API authentication, but they must not bypass the shared inference lifecycle.

Batch jobs must still use the same internal logic for:

* request ID generation
* usage accounting
* token accounting
* quota finalization
* Postgres audit records
* ClickHouse event emission
* Sentry tracing
* timeout handling
* vLLM error handling
* retry-safe state updates

There must not be two separate inference paths where online requests are properly tracked but batch jobs directly call vLLM without accounting.

## 21.7 Postgres and Redis queue recovery rule

Postgres is the source of truth for batch job state.

Redis may be used as the fast runtime queue, but Redis is not the durable source of truth.

If a batch job row is written to Postgres but Redis enqueue fails, the system must be able to recover.

A recovery scanner should periodically find Postgres batch jobs stuck in queued/runnable states and re-enqueue them if needed.

This prevents jobs from being permanently lost due to a Redis enqueue failure.

## 21.8 Critical usage record rule

Critical usage and billing-relevant records must be recoverable.

Postgres is the preferred durable store for correctness-critical request audit and usage records.

A local durable spool may be used only as a fallback when Postgres or ClickHouse is temporarily unavailable.

ClickHouse is not the source of truth for critical usage correctness.

ClickHouse receives analytics copies of events, but the system must not depend on ClickHouse to decide whether usage happened.

## 21.9 Redis outage rule

Redis is used for live runtime state such as rate limits, token counters, concurrency counters, queues, locks, and overload flags.

If Redis is unavailable, public online inference requests should fail closed instead of allowing unlimited GPU traffic.

The service should return a controlled overload or dependency-unavailable response rather than letting requests bypass quota and rate limits.

Internal/admin behavior can be decided separately, but public API traffic must not ignore Redis failure.

## 21.10 Token accounting rule

Token accounting must use the tokenizer for the same model family being served by vLLM whenever possible.

The gateway should not use a generic tokenizer if it causes large accounting drift.

Prompt token estimation should happen before admission and quota reservation.

Final token accounting should happen after completion, failure, or client disconnect.

If a streaming request disconnects before exact usage is available, store the best available generated-token count and mark the request as partial/client_disconnected.

Do not silently treat partial usage as a normal completed request.

## 21.11 Client disconnect status rule

`client_disconnected` is an internal request status.

If the service uses status code `499`, it should be treated as an observability/logging convention, not as a guaranteed HTTP response received by the client.

When a client disconnects, the system should:

* cancel upstream vLLM generation if possible
* stop wasting GPU work
* decrement concurrency counters
* finalize partial usage
* write a recoverable audit/usage record
* emit analytics event
* avoid leaking Redis counters

## 21.12 Single-node availability rule

The v1 design is production-style for a single GPU node, but it is not highly available.

One vLLM process using tensor parallelism across four GPUs means the four GPUs act as one logical model worker.

If one GPU fails, the model worker may become unhealthy.

If the Vast AI container dies, inference serving is unavailable.

The coding agent must not describe this as HA.

High availability requires an additional independent inference node or fallback worker, which is out of scope for v1.

## 21.13 Sentry non-critical-path rule

Sentry must never be in the request-critical path.

If Sentry is slow, unreachable, or down:

* online inference must continue
* batch jobs must continue
* ClickHouse flushing must continue
* Postgres writes must continue
* local logs must still be written

Sentry is for debugging and tracing failures, not for correctness.

The coding agent should not block request handling on Sentry delivery.

## 21.14 Public exposure rule

Only the public OpenAI-compatible inference API should be exposed through Cloudflare Tunnel.

The following must not be publicly exposed:

* vLLM direct port
* FastAPI internal/admin routes
* `/metrics`
* debug routes
* Prometheus
* Grafana unless separately protected
* Redis
* Postgres
* ClickHouse
* DCGM Exporter
* Node/system exporter
* batch worker internals

Internal access should happen over localhost, Tailscale, or another private network.

```