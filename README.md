# Samvara

A commitment-ratchet app backed by Beeminder. You commit to a clean streak of a
fixed length with money at stake. Finish clean and you deliberately choose the
next (usually longer) rung. Slip, miss, or let the deadline pass, and the stake
is charged and you recommit — same length, higher stake. The rung never gets
shorter.

This repo contains a **static frontend** (the bundled app: a Goals tab for the
ratchet and a Data tab of private daily tallies with graphs and ratios), a
**portable API backend** that holds the Beeminder token, runs the ratchet
logic, charges money, and persists state, and an **Android shell app** — the
same frontend in a WebView plus native deadline notifications (see
[The Android app](#the-android-app)).

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
- boot error handling: a failed first data-load shows a "Couldn't reach the
  server" card with a Retry button instead of an eternal "Loading…", and an
  expired session (401) clears itself and lands on the sign-in gate;
- a dashboard empty state, a `<title>`, and a favicon link;
- the **Data tab**: five private daily tallies with +1/−1 buttons (the server's
  calendar decides what "today" is — `METRICS_TZ`), bar graphs with a trailing
  7-day average, and days-with-data ratios;
- self-hosted **Newsreader** (`frontend/fonts/`): the raw export preconnects to
  Google Fonts but never loads the family, and Google's static subsets can't
  render the ṃ in "Saṃvara" anyway — Newsreader has no precomposed U+1E43 and
  builds it from m + combining dot (U+0323), which only a custom subset
  carries. Three woff2 files, served same-origin, no Google callout.

All of those edits live in `frontend/src/app.html`. The design tool's export is
one 800KB single-line file with the app embedded as a JSON string — unreadable
and hostile to diffs — so the repo keeps it **unpacked**: `src/app.html` is the
decoded app (readable, diffable, the file you edit) and `src/shell.html` is the
untouched runtime shell. The build recomposes them losslessly
(`scripts/pack_bundle.py`; the round-trip is byte-identical).

To import a fresh export from the design tool, unpack it next to the current
source and merge deliberately — never paste it over:

```
scripts/unpack_bundle.py ~/Downloads/export.html /tmp/fresh
diff frontend/src/app.html /tmp/fresh/app.html
```

The build guard still refuses to ship a bundle carrying the mock gate or a
personal address, so an unmerged export fails the build instead of leaking.

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
  tests/
    test_ratchet.py    parity tests pinning the mock's semantics
    test_auth.py       OTP flow, brute-force caps, tokens, sign-out revocation
    test_beeminder.py  charge-client rails: floor/cap, dryrun, failure modes
    test_money.py      HTTP-layer money invariants: races, ledger, edge cases
    test_api.py        dashboard ordering, daily-metric tallies, day boundary
  Dockerfile       single-worker non-root container, SQLite on a /data volume
  requirements.txt

frontend/
  src/
    app.html       the app's actual HTML/JS, unpacked and readable — EDIT THIS
    shell.html     bundle runtime/fonts/resources — machine territory
  fonts/           self-hosted Newsreader woff2 (incl. the ṃ-decomposition subset)
  index.html       generated from src/ by the build (git-ignored)
  api-client.js    the REAL fetch client (drop-in for the mock)
  config.example.js   copy to config.js per environment (git-ignored)

android/           WebView shell + native deadline notifications (see below)

scripts/
  build-frontend.sh     assembles dist/ for static hosting
  pack_bundle.py        recomposes frontend/index.html from frontend/src/
  unpack_bundle.py      splits an exported bundle into src/ (for re-imports)
  transform_bundle.py   strips the bundled mock, injects the config loader

.github/workflows/
  pages.yml          build + deploy the frontend to GitHub Pages (auto-retries
                     GitHub's transient deploy flake once)
  tick.yml           cron: POST /v1/tick
  backend-tests.yml  the money-path test suite on every push — red means
                     do not deploy the backend

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

Run the tests (domain parity, auth, and the money-path invariants — no network
needed; every Beeminder call is faked at the boundary):

```
cd backend
python -m pytest -q
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
and the auth endpoints requires `Authorization: Bearer <token>` — either a
session token from the OTP flow (what the browser uses) or the static
`API_TOKEN` (what the cron tick uses).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/v1/health` | Liveness (no auth). Effective config included only with a valid token. |
| POST | `/v1/auth/send-code` | Email a one-time sign-in code to the server's `AUTH_EMAIL`. Always 204. |
| POST | `/v1/auth/verify-code` | Exchange `{email, code}` for a 30-day session token. |
| POST | `/v1/auth/sign-out` | Revoke the presented session token server-side. Always 204. |
| GET | `/v1/commitments` | List all commitments. |
| GET | `/v1/commitments/{id}` | One commitment. |
| POST | `/v1/commitments` | Create `{name, base_days, base_stake}`. |
| POST | `/v1/commitments/{id}/confirm-clean` | Rung finished clean; await decision. No charge. |
| POST | `/v1/commitments/{id}/choose-next` | Start the next rung `{days, stake}`. No charge. |
| POST | `/v1/commitments/{id}/slip` | Report a slip. `{dryRun,raise,days,stake}`. Charges unless `dryRun`; 409 on an already-resolved rung or a duplicate report. |
| POST | `/v1/commitments/{id}/miss` | Same as slip, recorded as a miss. |
| POST | `/v1/commitments/{id}/auto-miss` | Grace expired (server's clock): charge + park. Idempotent; no-op before expiry. |
| POST | `/v1/tick` | Sweep all commitments past grace; charge + park each. |
| GET | `/v1/settings` | `{apiBaseUrl, recipient, totalCharged}`. |
| PATCH | `/v1/settings` | Merge a settings patch. |
| GET | `/v1/metrics` | Data-tab tallies: metric vocabulary, per-day series, today's date. |
| POST | `/v1/metrics/{key}/bump` | `{delta: 1\|-1}` on today's tally (floored at 0). The server's calendar (`METRICS_TZ`, default America/New_York) decides what "today" is. |

The ratchet rules, verbatim: a clean success advances the rung by **+1 day** and
holds the stake; a slip/miss holds the length and raises the stake by **+$1** by
default (overridable), and **never shortens** it. `suggestNextRung(days)` is
`days + 1`.

---

## Money safety

- **Dry-run by default.** `BEEMINDER_DRYRUN=true` routes every charge through
  Beeminder's own dryrun flag: the call is made and validated but no money moves.
  Verify the full flow, then set it to `false` to arm real charges. (The Fly
  config in this repo, `deploy/fly/fly.toml`, is **armed** — the deployed
  instance charges real money.)
- **Hard per-charge cap.** `MAX_CHARGE_USD` (default $50) is enforced server-side.
  Any single charge above it is refused regardless of what the client sends.
  The cap is **per charge** — there is no aggregate cap across commitments or
  time; `totalCharged` in settings is a ledger, not a limiter.
- **Charge-then-persist.** On a live slip/miss/auto-miss the server charges
  Beeminder *before* it mutates or saves state. A failed charge leaves the ledger
  untouched — you're never advanced without the charge landing, nor charged
  without it being recorded.
- **No interleaving charges twice.** All charging paths are serialized behind
  one lock and re-check state inside it: a slip that races the cron tick gets a
  409 instead of a second charge; an auto-miss that races a slip is a no-op
  (grace is re-checked against the *server's* clock); a double-clicked confirm
  is rejected as a duplicate within `LAPSE_DEBOUNCE_S` (default 10s); repeated
  ticks skip anything already parked.

These invariants are pinned by `tests/test_money.py` and `tests/test_beeminder.py`
— including "failed charge leaves state untouched" for every endpoint, the race
interleavings above, and a ledger-balance check (sum of charges ==
`totalCharged` == charged history).

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
credential. Signing out revokes the session **in the database**
(`/v1/auth/sign-out`), not just in the browser's localStorage.

No token or address ships in the static page — `config.js` holds only the API
base URL. The static `API_TOKEN` exists solely for the GitHub Actions tick and
never reaches a browser. The Beeminder token never leaves the server.

---

## The Android app

`android/` is a sideloadable shell, deliberately thin: the UI is
https://samvara.app in a WebView, so **every Pages deploy updates the app with
no reinstall**. The native layer adds the one thing a website can't — a
JobScheduler poller (~15 min, persists across reboots, pure AOSP so it runs on
GrapheneOS without Play services) that reads `/v1/commitments` and notifies
before money moves:

- deadline within **6h** on an active rung,
- deadline passed — the **24h confirmation window** is running,
- under **3h** left in that window (last call before the auto-charge),
- **auto-charged** and parked awaiting a recommit,
- the stored session died (**401**) — alerts are paused until you sign in again.

Each fires at most once per rung. The session token is copied out of the
page's localStorage after each load (the app never injects into the page);
sign-out clears it. Zero library dependencies — framework APIs only — so the
only artifact Gradle needs is the Android Gradle Plugin.

```
cd android
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 gradle assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
```

The build needs a full JDK (17+) and an Android SDK at the path in
`android/local.properties`. The APK is debug-signed, which is fine for
personal sideloading; installs upgrade in place as long as the same machine's
debug keystore signs them. On first launch: accept the notification prompt,
sign in, and (optionally) set battery usage to Unrestricted so Doze can't
delay the polls — though with a 24h grace window even heavily deferred jobs
have ample margin.
