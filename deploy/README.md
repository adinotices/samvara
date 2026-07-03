# Deploying the Samvara API to a cloud host

The frontend is static and goes to GitHub Pages (see the repo README). The API
is a portable Docker container that runs the same anywhere. Two worked examples
follow; any Docker host works the same way.

## What the API needs, everywhere

- A writable volume for the SQLite file (`/data`), so state survives restarts.
- HTTPS in front of it. The page is served from `https://samvara.app`; browsers
  refuse to let an HTTPS page call a plain-HTTP API (mixed content). Terminate
  TLS at a reverse proxy or the platform's load balancer.
- `ALLOWED_ORIGINS` set to the exact frontend origin (e.g. `https://samvara.app`),
  or CORS will block the browser.
- A single running instance, or a shared database. The store serializes user
  actions and `/tick` with an in-process lock, which only holds within one
  process. Run one container/machine, or swap the `Store` for a real DB.

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
