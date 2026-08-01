# Samvara

A commitment-ratchet app connected to Beeminder. You commit to a clean streak of a
fixed length with money at stake. Finish clean and you deliberately choose the
next (usually longer) rung. Slip, miss, or let the deadline pass, and the stake
is charged and you recommit — same length, higher stake. By default, the rung never gets
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
>
> **The backend is multi-tenant (separate accounts, separate data — see
> [The database](#the-database)) but still has exactly ONE Beeminder token,
> configured once for the whole server.** Every user's charge goes through
> that same token, to that same Beeminder account. That's fine for inviting
> people you trust with your own Beeminder account; it is not a "each user
> pays for themselves" setup — that needs a per-user payment integration
> (Beeminder OAuth or a real payment processor), which this port does not add.

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
  Google Fonts but never loads the family. Three woff2 files, served
  same-origin, no Google callout;
- the wordmark's **ṃ is drawn, not typed**: no Newsreader subset carries a
  precomposed U+1E43 (it composes m + U+0323, which desktop Blink shapes but
  the Android WebView's font selection never reaches), and system fonts render
  a mismatched fallback glyph. The headline wordmarks use an `.mdot` span — a
  `currentColor` CSS dot under a plain m — that scales in em and cannot fall
  back to anything;
- the **Dark/Light toggle persists** (`localStorage 'samvara.dark'`) and
  reports theme changes to the Android shell via `window.SamvaraShell` so the
  system bars follow the page.

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
    main.py          FastAPI app — the only HTTP layer; wires the pieces below
    ratchet.py       pure state transitions (no I/O) — the domain rules
    beeminder.py     the ONE place money moves; charge caps + dryrun live here
    db.py            SQLAlchemy Core table definitions + engine factory
    store.py         persistence, multi-tenant (every table user_id-scoped);
                     Postgres in prod, SQLite for local dev/tests
    auth.py          email OTP sign-in: code issue/verify, 30-day sessions,
                     the invite gate (signin_allowed)
    security.py      three auth dependencies: current_user (session only —
                     every user route), require_auth (session or the static
                     token — /v1/tick only), require_admin (static token or
                     the owner's session — /v1/admin/*)
    logging_config.py   structured JSON logging + request-id correlation
    config.py        all env-driven configuration
  migrations/        Alembic — schema evolution from here forward
  tests/
    test_ratchet.py         parity tests pinning the mock's semantics
    test_auth.py            OTP flow, invite gate, admin routes, sessions
    test_beeminder.py       charge-client rails: floor/cap, dryrun, failure modes
    test_money.py           HTTP-layer money invariants: races, ledger, edges,
                            cross-user isolation of the ledger
    test_api.py             dashboard ordering, daily tallies, cross-user
                            isolation of commitments and settings
    test_access_requests.py "request access" persistence + notification
    _helpers.py             shared signin() for the multi-tenant test files
  Dockerfile         non-root container; runs `alembic upgrade head` before
                     every start (see the Dockerfile's own comment on why
                     that ordering matters)
  alembic.ini
  requirements.txt

frontend/
  src/
    app.html       the app's actual HTML/JS, unpacked and readable — EDIT THIS
    shell.html     bundle runtime/fonts/resources — machine territory
  fonts/           self-hosted Newsreader woff2 (the wordmark's ṃ itself is CSS)
  index.html       generated from src/ by the build (git-ignored)
  api-client.js    the REAL fetch client (drop-in for the mock)
  config.example.js   copy to config.js per environment (git-ignored)

android/           WebView shell + native deadline notifications (see below)

scripts/
  build-frontend.sh     assembles dist/ for static hosting
  pack_bundle.py        recomposes frontend/index.html from frontend/src/
  unpack_bundle.py      splits an exported bundle into src/ (for re-imports)
  transform_bundle.py   strips the bundled mock, injects the config loader
  import_legacy_db.py   one-time: a pre-multi-tenant-port database -> the
                        current schema, as user #1 (see its own docstring)

.github/workflows/
  pages.yml           build + deploy the frontend to GitHub Pages (auto-retries
                      GitHub's transient deploy flake once)
  tick.yml            cron: POST /v1/tick
  backend-tests.yml   the money-path test suite on every push — red means
                      do not deploy the backend
  android-build.yml   compiles the Android shell on every push touching android/
  security-scans.yml  pip-audit (backend deps) + gitleaks (full git history)

deploy/
  digitalocean/    docker-compose (API + Postgres) + notes
  fly/             fly.toml
  README.md        cloud deploy + Postgres + tick-scheduling notes

.env.example       backend configuration template
```

---

## Quickstart (local)

### 1. Backend

```
cd backend
pip install -r requirements.txt
python3 -m alembic upgrade head    # creates a local SQLite db (or your DATABASE_URL)
AUTH_MODE=none uvicorn app.main:app --reload
```

`AUTH_MODE=none` skips auth for local dev — the sign-in gate then accepts any
email and any 6-digit code (all resolving to one fixed dev user), no email
service needed. The API is now at `http://localhost:8000`; check
`http://localhost:8000/v1/health`. With no Beeminder token set,
read/create/confirm/choose and **dry-run** slips all work; live charges are
refused until a token is configured.

By default this runs on a local SQLite file. Point `DATABASE_URL` at a
Postgres instance to develop against the same database engine production
uses — see [The database](#the-database) below.

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

## The database

Multi-tenant: every commitment, tally, and setting belongs to a user, and
every store method that touches one takes a user id and filters on it — see
`tests/test_api.py` and `tests/test_money.py`'s isolation tests, which assert
that directly rather than trusting call sites to remember it.

**Postgres in production, SQLite for local dev and tests.** Set `DATABASE_URL`
to a `postgresql+psycopg://...` URL for production; leave it unset and the app
falls back to a SQLite file at `SAMVARA_DB`. This isn't just a durability
preference: the row-level locking the charging endpoints use
(`store.commitment_lock`, a real `SELECT ... FOR UPDATE`) is a genuine lock on
Postgres and a silent no-op on SQLite — same-process safety on SQLite still
holds (an `asyncio.Lock` in `main.py` serializes every charge sequence within
one process), but SQLite was never meant to be the multi-tenant production
target.

**Migrations are Alembic**, from `backend/migrations/`:

```
cd backend
DATABASE_URL=postgresql+psycopg://... python3 -m alembic upgrade head
```

The Docker image runs this itself before every start (see the Dockerfile), so
a normal deploy doesn't need a separate migration step. There is no migration
history before the multi-tenant port — the pre-port database was raw sqlite3
with no migration tooling at all, so "baseline schema" is where Alembic's
history starts.

**Bringing over a pre-port (single-tenant) database**: that's not something
Alembic does — a bespoke old format needs a bespoke one-time reader, not a
schema diff. Use `scripts/import_legacy_db.py` (see its docstring; run with
`--dry-run` first). It creates one user from the old database's owner email
and attributes every commitment, tally, and setting to them.

**Sign-in is invite-gated by default** (`SIGNUP_MODE=invite`, see
`.env.example`): only the configured `AUTH_EMAIL` (the app owner — always
allowed, in any mode) and addresses added via `POST /v1/admin/invites` can
complete sign-in. `SIGNUP_MODE=open` allows anyone who completes the OTP flow.
Manage invites with the static `API_TOKEN` or an owner session:

```
curl -X POST https://api.samvara.app/v1/admin/invites \
  -H "Authorization: Bearer $API_TOKEN" -H "Content-Type: application/json" \
  -d '{"email": "someone@example.com", "note": "optional"}'
```

**Account deletion** (`DELETE /v1/account`, any signed-in user, on
themselves) is a real hard delete — every commitment, tally, and setting row,
gone in one transaction, not a soft-delete flag. The one exception: charge
history isn't currently erased by this — see `Store.delete_user`'s docstring.
There's no confirmation step or grace period at the API layer; that UX (and
the rest of account management — verification, export, session hardening)
is a client-side / product concern layered on top of this primitive.

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

All routes are under `/v1`. Three different bearer checks, not one — see
`security.py`:

- **`current_user`** — a session token only, resolved to the signed-in user.
  Every user-data route (commitments, settings, metrics, account) depends on
  this. The static `API_TOKEN` is deliberately **not** accepted here: there's
  no "current user" it could resolve to, so multi-tenant it can't be a
  god-token the way it was in the single-tenant version of this API.
- **`require_auth`** — a session, or the static `API_TOKEN`. Used only by
  `/v1/tick` (the cron sweep has no "current user" either — it spans everyone).
- **`require_admin`** — the static `API_TOKEN`, or a session belonging to
  `AUTH_EMAIL` (the app owner). Used only by `/v1/admin/*` (invite management).

`AUTH_MODE=none` (local dev) disables all of this — every request resolves to
one fixed dev user.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/v1/health` | Liveness (no auth): is the process up. Effective config included only with a valid token. |
| GET | `/v1/health/ready` | Readiness (no auth): is the database reachable. Returns 503 if not — this is what a load balancer or orchestrator should point at, not `/v1/health`. |
| POST | `/v1/auth/send-code` | Email a one-time sign-in code, if the address is allowed to sign in (the owner, always; anyone else per `SIGNUP_MODE`/invites). Always 204. |
| POST | `/v1/auth/verify-code` | Exchange `{email, code}` for a 30-day session token. First successful verify for a new address creates the account. |
| POST | `/v1/auth/sign-out` | Revoke the presented session token server-side. Always 204. |
| DELETE | `/v1/account` | **`current_user`.** Hard-delete the signed-in user's account: every commitment, tally, and setting, gone in one transaction. |
| POST | `/v1/access-requests` | `{name, email, message}` from the sign-in gate's denied path. No auth. Persisted, then a best-effort notification email to `AUTH_EMAIL`. Always 204. |
| POST | `/v1/admin/invites` | **`require_admin`.** `{email, note?}` — add an address to the sign-in allowlist. |
| GET | `/v1/admin/invites` | **`require_admin`.** List invited addresses. |
| GET | `/v1/commitments` | **`current_user`.** List the signed-in user's commitments. |
| GET | `/v1/commitments/{id}` | **`current_user`.** One commitment (404 if it isn't yours). |
| POST | `/v1/commitments` | **`current_user`.** Create `{name, base_days, base_stake}`. |
| POST | `/v1/commitments/{id}/confirm-clean` | **`current_user`.** Rung finished clean; await decision. No charge. |
| POST | `/v1/commitments/{id}/choose-next` | **`current_user`.** Start the next rung `{days, stake}`. No charge. |
| POST | `/v1/commitments/{id}/slip` | **`current_user`.** Report a slip. `{dryRun,raise,days,stake}`. Charges unless `dryRun`; 409 on an already-resolved rung or a duplicate report. |
| POST | `/v1/commitments/{id}/miss` | **`current_user`.** Same as slip, recorded as a miss. |
| POST | `/v1/commitments/{id}/auto-miss` | **`current_user`.** Grace expired (server's clock): charge + park. Idempotent; no-op before expiry. |
| POST | `/v1/tick` | **`require_auth`.** Sweep every user's commitments and pending penalties past grace; charge + park each. |
| GET | `/v1/settings` | **`current_user`.** `{apiBaseUrl, recipient, totalCharged}`, per user. |
| PATCH | `/v1/settings` | **`current_user`.** Merge a settings patch. |
| GET | `/v1/metrics` | **`current_user`.** Data-tab tallies: metric vocabulary, per-day series, today's date. |
| POST | `/v1/metrics/{key}/bump` | **`current_user`.** `{delta: 1\|-1}` on today's tally (floored at 0). The signed-in user's own timezone decides what "today" is. |

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
   the address is allowed to sign in — the owner (`AUTH_EMAIL`), always; anyone
   else only per `SIGNUP_MODE` (see [The database](#the-database)) — a 6-digit
   code is emailed via [Resend](https://resend.com). The response is `204` in
   every case, so the endpoint can't be used to probe which addresses are
   allowed.
2. `/v1/auth/verify-code` exchanges the code for a 30-day session token, which
   the browser keeps in `localStorage` and sends as a Bearer header. The first
   successful verify for a new address creates the account — there's no
   separate registration step.

Abuse limits, all server-side: a code dies after **5 wrong guesses** or **10
minutes**; sends are limited to **one email per minute** (repeats inside the
window keep the existing code valid); only **SHA-256 hashes** of codes and
session tokens are stored, so a copied database file contains no usable
credential. Signing out revokes the session **in the database**
(`/v1/auth/sign-out`), not just in the browser's localStorage.

No token or address ships in the static page — `config.js` holds only the API
base URL. The static `API_TOKEN` grants no access to any user's data (see
[API](#api)) — it exists solely for the GitHub Actions tick and invite
management, and never reaches a browser. The Beeminder token never leaves the
server.

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

Two more shell behaviors worth knowing:

- **Cold starts clear the WebView HTTP cache**, so every open shows the latest
  deploy — WebView's cache heuristics otherwise serve a stale page well past
  its max-age. localStorage (session, theme) survives.
- **The system bars follow the page theme.** The page calls
  `window.SamvaraShell.onTheme()` on boot and on every Dark/Light toggle; the
  shell recolors the inset strip, flips status-icon contrast, and remembers
  the theme so the next cold start opens in the right colors before the page
  paints.

```
cd android
JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 gradle assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
```

The build needs a full JDK (17+) and an Android SDK at the path in
`android/local.properties` — this file is per-machine and git-ignored, so
create it yourself (`sdk.dir=/path/to/Android/sdk`) or let Android Studio
generate it on first open. The APK is debug-signed, which is fine for
personal sideloading; installs upgrade in place as long as the same machine's
debug keystore signs them. On first launch: accept the notification prompt,
sign in, and (optionally) set battery usage to Unrestricted so Doze can't
delay the polls — though with a 24h grace window even heavily deferred jobs
have ample margin.
