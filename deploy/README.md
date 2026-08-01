# Deploying the Samvara API to a cloud host

The frontend is static and goes to GitHub Pages (see the repo README). The API
is a portable Docker container that runs the same anywhere. Two worked examples
follow; any Docker host works the same way.

## What the API needs, everywhere

- A database. **Set `DATABASE_URL`** to a Postgres connection string
  (`postgresql+psycopg://user:pass@host/db`) — this is the multi-tenant path
  and what the money-side row locking (`store.commitment_lock`, used by every
  charging endpoint) is real on. Leaving `DATABASE_URL` unset falls back to a
  SQLite file at `SAMVARA_DB`, which needs a writable volume (`/data`) to
  survive restarts and, on that path, only ever runs correctly as a single
  instance (see below) — SQLite has no real row locking, so the
  cross-process safety `commitment_lock` provides on Postgres is a silent
  no-op there.
- **Run migrations before first boot**: `cd backend && DATABASE_URL=... python3
  -m alembic upgrade head`. The Docker image's CMD already does this itself on
  every start (`alembic upgrade head && uvicorn ...`), so a normal deploy
  doesn't need a separate step — this matters if you're running the app some
  other way (bare `uvicorn`, a different process manager).
- If you're carrying over an existing single-tenant database from before this
  port, `scripts/import_legacy_db.py` migrates it in as user #1 — see the
  script's docstring; run it with `--dry-run` first.
- HTTPS in front of it. The page is served from `https://samvara.app`; browsers
  refuse to let an HTTPS page call a plain-HTTP API (mixed content). Terminate
  TLS at a reverse proxy or the platform's load balancer.
- `ALLOWED_ORIGINS` set to the exact frontend origin (e.g. `https://samvara.app`),
  or CORS will block the browser.
- A single running instance still, for now, **even on Postgres** — the
  Dockerfile is pinned to `--workers 1` and the `_charge_lock` in `main.py`
  only serializes within one process. `commitment_lock`'s real Postgres row
  locking is what would make more workers safe, but that hasn't been
  validated under real multi-worker load yet (see the Dockerfile's comment on
  this). Don't raise the worker count without doing that load testing first.

## DigitalOcean (droplet + Docker Compose)

```
# on the droplet, repo checked out:
cp .env.example deploy/digitalocean/.env     # then edit it
docker compose -f deploy/digitalocean/docker-compose.yml up -d --build
```

Put Caddy or nginx in front for TLS, or use a DigitalOcean load balancer with a
managed cert. Point `api.samvara.app` (or similar) at it and set that URL as the
frontend's `SAMVARA_API_BASE_URL`.

DigitalOcean App Platform works too: point it at `backend/Dockerfile`, attach a
persistent volume at `/data`, and set the same environment variables.

## Fly.io

See `deploy/fly/fly.toml`. Fly gives you HTTPS and a health check out of the box;
the single mounted volume keeps SQLite durable.

## Scheduling the tick without GitHub Actions

If you move off GitHub (or want tighter timing than GitHub cron's best-effort
schedule), drive `/v1/tick` from the host instead. A crontab line:

```
*/15 * * * * curl -fsS -X POST https://api.samvara.app/v1/tick \
  -H "Authorization: Bearer $API_TOKEN" >/dev/null 2>&1
```

The 24h grace window means exact timing doesn't matter; you only need a tick to
land sometime within the grace period after a deadline.

## Moving hosts later

Because everything host-specific is an environment variable and the data is one
SQLite file:

1. Copy `/data/samvara.db` from the old host to the new one.
2. Bring up the container there with the same env vars.
3. Update the frontend's `SAMVARA_API_BASE_URL` to the new URL and redeploy the
   page (or just change it in the in-app Settings screen, which overrides the
   base URL locally).

No code changes.
