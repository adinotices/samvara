# Samvara

A commitment-ratchet app backed by Beeminder. You commit to a clean streak of a
fixed length with money at stake. Finish clean and you deliberately choose the
next (usually longer) rung. Slip, miss, or let the deadline pass, and the stake
is charged and you recommit — same length, higher stake. The rung never gets
shorter.

This repo contains a **static frontend** (the bundled app, unchanged except its
sign-in gate, which is rewired to a real server-side email login) and a
**portable API backend** that holds the Beeminder token, runs the ratchet
logic, charges money, and persists state.

> **This app moves real money.** Charges go through Beeminder to whoever owns the
> configured Beeminder token. Read [Money safety](#money-safety) before you arm
> real charges. The backend ships with charges in **dry-run by default** and a
> hard per-charge cap.

---

## How it fits together

```
   Browser (samvara.app, GitHub Pages)                 API server (anywhere)
   ┌───────────────────────────────┐                  ┌──────────────────────┐
   │ index.html  (bundled app)      │   fetch  /v1/*   │ FastAPI              │
   │ config.js   window.SAMVARA_… ──┼─────────────────▶│  ratchet logic       │
   │ api-client.js (real, fetch)    │   Bearer token   │  Beeminder charges ──┼──▶ Beeminder
   └───────────────────────────────┘                  │  SQLite persistence  │
                                                        └──────────────────────┘
                                                                 ▲
   GitHub Actions cron ── POST /v1/tick ──────────────────────────┘
   (charges missed deadlines even when nobody has the app open)
```

The frontend was built against a mock `api-client.js` that defined the entire
API contract. The real client here is a **drop-in** for that mock — same
exports, same shapes. The build strips the bundled mock client so the page
loads the real one (see [The frontend transform](#the-frontend-transform)),
and `frontend/index.html` carries a few source-level edits over the raw
export:

- the sign-in gate — originally a demo that generated its code in the browser
  and displayed it on screen — is rewired to the server's OTP endpoints (see
  [Sign-in](#sign-in));
- the boot line `import('./api-client.js')` resolves via
  `new URL(..., location.href)` — a relative module specifier cannot resolve
  from the bundle's document-swap context, which left the app stuck on
  "Loading…" forever (the mock never hit this path, so the raw export ships
  broken here);
- a dashboard empty state, a `<title>`, and a favicon link.

If you ever re-export a fresh bundle, those edits must be reapplied; the build
guard refuses to ship a bundle that still carries the mock gate or a personal
address.

Why split this way: GitHub Pages is static and can't safely hold a Beeminder
token or charge money, so anything involving the token or money lives in the
backend. The app already has a configurable API base URL, so **moving the
backend from GitHub-Pages-plus-a-server to DigitalOcean or Fly is a URL change,
not a rewrite.**

---

## Repository layout

```
backend/
  app/
    main.py        FastAPI app — the only HTTP layer; wires the pieces below
    ratchet.py     pure state transitions (no I/O) — the domain rules
    beeminder.py   the ONE place money moves; charge caps + dryrun live here
    store.py       SQLite persistence behind a small swappable interface
    auth.py        email OTP sign-in: code issue/verify, 30-day sessions
    security.py    bearer auth (session or static token) + request schemas
    config.py      all env-driven configuration
  tests/test_ratchet.py   parity tests pinning the mock's semantics
  Dockerfile       single-worker container, SQLite on a /data volume
  requirements.txt

frontend/
  index.html       the raw bundle (source; transformed at build time)
  api-client.js    the REAL fetch client (drop-in for the mock)
  config.example.js   copy to config.js per environment (git-ignored)

scripts/
  build-frontend.sh     assembles dist/ for static hosting
  transform_bundle.py   strips the bundled mock, injects the config loader

.github/workflows/
  pages.yml        build + deploy the frontend to GitHub Pages
  tick.yml         cron: POST /v1/tick

deploy/
  digitalocean/    docker-compose + notes
  fly/             fly.toml
  README.md        cloud deploy + tick-scheduling notes

.env.example       backend configuration template
```

---

## Quickstart (local)

### 1. Backend

```
cd backend
pip install -r requirements.txt
AUTH_MODE=none uvicorn app.main:app --reload
```

`AUTH_MODE=none` skips auth for local dev — the sign-in gate then accepts any
email and any 6-digit code, no email service needed. The API is now at
`http://localhost:8000`; check `http://localhost:8000/v1/health`. With no
Beeminder token set, read/create/confirm/choose and **dry-run** slips all work;
live charges are refused until a token is configured.

Run the parity tests:

```
cd backend
python -m pytest -q          # or: python tests/test_ratchet.py
```

### 2. Frontend

```
# frontend/config.js already points at http://localhost:8000 with no token.
scripts/build-frontend.sh
cd dist && python3 -m http.server 8080
```

Open `http://localhost:8080`. The app boots, loads the real client, and talks to
your local API. (Serve over http/localhost — opening `index.html` from `file://`
won't allow the fetch calls.)

---

## Deploying

### Frontend → GitHub Pages

1. Push this repo to GitHub; enable Pages (Settings → Pages → Source: GitHub
   Actions).
2. Add repository secrets: `SAMVARA_API_BASE_URL` (your API's public HTTPS URL)
   for the Pages build, and `SAMVARA_API_TOKEN` (matches the server's
   `API_TOKEN`) for the tick workflow only — **no token is ever baked into the
   published page**; browsers sign in via the email OTP flow.
3. (Optional) set repo variable `SAMVARA_CNAME` if not using `samvara.app`, and
   configure the custom domain in Pages settings + DNS.
4. Push to `main`. `pages.yml` generates `config.js` from the secrets, builds
   `dist/`, and publishes.

### Backend → any Docker host

See `deploy/README.md`. Short version: set the environment from `.env.example`,
give it a persistent `/data` volume, put HTTPS in front, and set
`ALLOWED_ORIGINS` to your frontend origin. DigitalOcean compose file and a Fly
config are included.

### The tick

`tick.yml` calls `POST /v1/tick` every 15 minutes so a missed deadline is charged
and parked even when the app isn't open. It needs the same two secrets. If you
leave GitHub, drive the tick from host cron instead (see `deploy/README.md`).

---

## The frontend transform

The bundle resolves its API client from `window.__resources.apiClient` (the
baked-in mock) *before* falling back to `./api-client.js`. `scripts/transform_bundle.py`
removes the `apiClient` entry from the bundle's `ext_resources` (and drops the
now-orphaned mock asset), so `window.__resources.apiClient` is undefined and the
app loads the real `./api-client.js` served next to it. It also injects
`<script src="config.js">` into `<head>` so `window.SAMVARA_CONFIG` exists before
boot. As a last step it refuses to ship a bundle containing the mock sign-in
gate or a personal address, so a careless re-export of the raw bundle fails the
build instead of leaking.

---

## API

All routes are under `/v1`. When `AUTH_MODE=token`, everything except health
and the two auth endpoints requires `Authorization: Bearer <token>` — either a
session token from the OTP flow (what the browser uses) or the static
`API_TOKEN` (what the cron tick uses).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/v1/health` | Liveness (no auth). Effective config included only with a valid token. |
| POST | `/v1/auth/send-code` | Email a one-time sign-in code to the server's `AUTH_EMAIL`. Always 204. |
| POST | `/v1/auth/verify-code` | Exchange `{email, code}` for a 30-day session token. |
| GET | `/v1/commitments` | List all commitments. |
| GET | `/v1/commitments/{id}` | One commitment. |
| POST | `/v1/commitments` | Create `{name, base_days, base_stake}`. |
| POST | `/v1/commitments/{id}/confirm-clean` | Rung finished clean; await decision. No charge. |
| POST | `/v1/commitments/{id}/choose-next` | Start the next rung `{days, stake}`. No charge. |
| POST | `/v1/commitments/{id}/slip` | Report a slip. `{dryRun,raise,days,stake}`. Charges unless `dryRun`. |
| POST | `/v1/commitments/{id}/miss` | Same as slip, recorded as a miss. |
| POST | `/v1/commitments/{id}/auto-miss` | Grace expired: charge + park. Idempotent. |
| POST | `/v1/tick` | Sweep all commitments past grace; charge + park each. |
| GET | `/v1/settings` | `{apiBaseUrl, recipient, totalCharged}`. |
| PATCH | `/v1/settings` | Merge a settings patch. |

The ratchet rules, verbatim: a clean success advances the rung by **+1 day** and
holds the stake; a slip/miss holds the length and raises the stake by **+$1** by
default (overridable), and **never shortens** it. `suggestNextRung(days)` is
`days + 1`.

---

## Money safety

- **Dry-run by default.** `BEEMINDER_DRYRUN=true` routes every charge through
  Beeminder's own dryrun flag: the call is made and validated but no money moves.
  Verify the full flow, then set it to `false` to arm real charges.
- **Hard per-charge cap.** `MAX_CHARGE_USD` (default $50) is enforced server-side.
  Any single charge above it is refused regardless of what the client sends.
- **Charge-then-persist.** On a live slip/miss/auto-miss the server charges
  Beeminder *before* it mutates or saves state. A failed charge leaves the ledger
  untouched — you're never advanced without the charge landing, nor charged
  without it being recorded.
- **Idempotent auto-miss.** Repeated ticks or retries can't double-charge a
  commitment that's already been auto-missed and parked.

### Sign-in

Sign-in is a real server-side email OTP, not a client-side check:

1. The app posts the entered address to `/v1/auth/send-code`. If (and only if)
   it matches the server's `AUTH_EMAIL`, a 6-digit code is emailed via
   [Resend](https://resend.com). The response is `204` in every case, so the
   endpoint can't be used to probe which address is allowed.
2. `/v1/auth/verify-code` exchanges the code for a 30-day session token, which
   the browser keeps in `localStorage` and sends as a Bearer header.

Abuse limits, all server-side: a code dies after **5 wrong guesses** or **10
minutes**; sends are limited to **one email per minute** (repeats inside the
window keep the existing code valid); only **SHA-256 hashes** of codes and
session tokens are stored, so a copied database file contains no usable
credential.

No token or address ships in the static page — `config.js` holds only the API
base URL. The static `API_TOKEN` exists solely for the GitHub Actions tick and
never reaches a browser. The Beeminder token never leaves the server.
