# Postgres Connectivity From Vast

Status: live as of 2026-05-28.

This is the private Postgres path for the GPU inference backend running on Vast.
Do not send raw Postgres traffic through Cloudflare HTTP proxying or the wildcard
`*.ansuman.yral.com` DNS route.

## Route

```text
FastAPI on Vast
  -> Tailscale
  -> 100.78.17.101:15432 or 100.79.99.107:15432
  -> HAProxy fe_postgres_primary_local
  -> HAProxy be_postgres_primary
  -> ansuman-1 PostgreSQL primary, with ansuman-2 as backup/standby
```

Live HAProxy listeners:

```text
ansuman-1: 127.0.0.1:15432, 100.78.17.101:15432
ansuman-2: 127.0.0.1:15432, 100.79.99.107:15432
```

The original local listener remains in place for existing services. The new
listeners only add Tailscale access to the same HAProxy frontend.

## Verified State

Checked on 2026-05-28:

```text
ansuman-1 pg_is_in_recovery() = false
ansuman-2 pg_is_in_recovery() = true
ansuman-1 HAProxy service = active
ansuman-2 HAProxy service = active
ansuman-1 UFW allows 15432/tcp on tailscale0 from Anywhere
ansuman-2 UFW allows 15432/tcp on tailscale0 from Anywhere
Postgres role gpu_inference created
Postgres database gpu_inference created and owned by gpu_inference
pg_hba.conf allows gpu_inference/gpu_inference from 100.78.17.101/32 and 100.79.99.107/32
read/write check passed through the ansuman-1 HAProxy listener
read check passed through the ansuman-2 HAProxy listener
100.78.17.101:15432 TCP reachable
100.79.99.107:15432 TCP reachable
```

The UFW rule is intentionally tailnet-wide because Vast instances are
short-lived and will receive a new Tailscale IP each time. The exposure is still
limited to traffic arriving on `tailscale0`.

HAProxy config backups created during the change:

```text
ansuman-1: /etc/haproxy/haproxy.cfg.bak-gpu-pg-20260528T170452Z
ansuman-2: /etc/haproxy/haproxy.cfg.bak-gpu-pg-20260528T170520Z
ansuman-1: /etc/postgresql/16/main/pg_hba.conf.bak-gpu-inference-20260528T175830Z
ansuman-2: /etc/postgresql/16/main/pg_hba.conf.bak-gpu-inference-20260528T175830Z
```

## Application DSN

SQLAlchemy's `asyncpg` dialect supports multiple fallback hosts with repeated
`host=<host>:<port>` query parameters. This support was added in SQLAlchemy
`2.0.18`; the current lockfile resolves SQLAlchemy `2.0.50`.

Use this shape for the GPU inference service:

```text
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@/DBNAME?host=100.78.17.101:15432&host=100.79.99.107:15432
```

The local ignored `.env` has the real `gpu_inference` DSN.

All asyncpg multi-host entries must include an explicit port.

Application code now includes the SQLAlchemy async DB layer, `asyncpg` runtime
dependency, and initial Alembic schema migration `20260529_0001_phase6_schema.py`.
Run `make migrate` only against the intended database. API keys use the `an_...`
format from `docs/todo.md`, store only SHA-256 hashes, and keep a short prefix
for debugging.

Official reference:
`https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#asyncpg`

## Failover Semantics

This gives two levels of fallback:

1. If the app cannot connect to ansuman-1 HAProxy, SQLAlchemy can try ansuman-2
   HAProxy.
2. Each HAProxy frontend uses `be_postgres_primary`, where ansuman-1 is first
   and ansuman-2 is marked backup.

This does not make write failover automatic. If ansuman-1 PostgreSQL is down and
ansuman-2 is still a physical standby, writes will fail until ansuman-2 is
properly promoted and the cluster state is safe.

## Remaining Setup

Before enabling this in production:

```text
Install and join Tailscale on the Vast instance.
Run an app-level read/write migration test from the actual Vast instance.
```
