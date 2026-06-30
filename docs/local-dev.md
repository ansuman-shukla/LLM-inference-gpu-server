# Local Development

Use the Makefile targets as the project interface.

For Phase 7 Redis admission tests, unit and integration tests use an in-memory
FakeRedis and do not require a local Redis process.

To run the real local Redis process expected by the app:

```bash
make run-redis
```

This executes `redis-server` bound to `127.0.0.1:6379` through the uv-managed
script wrapper so the Makefile command still starts with `uv run`.
