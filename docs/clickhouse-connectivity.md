# ClickHouse Connectivity From Vast

Status: live as of 2026-05-28.

This is the private ClickHouse path for the GPU inference backend running on
Vast. It uses the existing HAProxy HTTPS frontend, not a guessed public hostname.

## Route

```text
FastAPI on Vast
  -> Tailscale
  -> https://100.78.17.101:8443 or https://100.79.99.107:8443
  -> HAProxy fe_clickhouse_https
  -> HAProxy be_clickhouse_http
  -> ansuman-1 active, ansuman-3 first backup, ansuman-2 second backup
```

The server certificate is currently self-signed, so application clients should
use encrypted HTTPS with certificate verification disabled unless the cert setup
is changed later.

## User

ClickHouse user created on all three ClickHouse nodes:

```text
user: gpu_inference
database: yral
grants: SELECT ON yral.*, INSERT ON yral.*
```

No ClickHouse admin, DDL, ALTER, DROP, or TRUNCATE grants were added.

## Verified State

Checked on 2026-05-28:

```text
ansuman-1 user exists with SELECT, INSERT on yral.*
ansuman-2 user exists with SELECT, INSERT on yral.*
ansuman-3 user exists with SELECT, INSERT on yral.*
ansuman-1 UFW allows 8443/tcp on tailscale0 from Anywhere
ansuman-2 UFW allows 8443/tcp on tailscale0 from Anywhere
https://100.78.17.101:8443 returned SELECT 1 with the gpu_inference user
https://100.79.99.107:8443 returned SELECT 1 with the gpu_inference user
```

The UFW rule is intentionally tailnet-wide because Vast instances are
short-lived and will receive a new Tailscale IP each time. The exposure is still
limited to traffic arriving on `tailscale0`.

## Application Settings

The local ignored `.env` has the real secret values. The shape is:

```text
CLICKHOUSE_URL="https://100.78.17.101:8443"
CLICKHOUSE_ALT_URL="https://100.79.99.107:8443"
CLICKHOUSE_DATABASE=yral
CLICKHOUSE_USER=gpu_inference
CLICKHOUSE_PASSWORD=<stored in local .env>
CLICKHOUSE_SECURE=true
CLICKHOUSE_VERIFY=false
```

Run the same HTTPS SELECT check from the actual Vast instance after it joins
Tailscale.


## Phase 10 application note

The backend now includes ClickHouse event models, a bounded in-memory analytics
collector, local JSONL spool for critical events, and a batch flusher. The DDL
entrypoint is:

```bash
make run-flusher  # worker process
uv run --env-file .env python -m backend.scripts.create_clickhouse_tables
```

Set `CLICKHOUSE_CLUSTER` to the real cluster name before creating distributed
tables. The ClickHouse user documented above currently has SELECT/INSERT only,
so DDL may need to be run with an admin or migration role.
