# Saṃvara: from personal app to consumer app on the App Store and Google Play

A review of the current codebase (web app, backend, Android shell) against what
shipping to consumers on both stores actually requires, and the list of work to
get there.

Reviewed at commit `c30e75a`. Backend test suite: **61 passed**.

---

## The short version

The engineering you have is good. The domain logic is clean, the money paths are
genuinely careful (charge-then-persist, one lock, per-charge cap, a real test
suite pinning race interleavings), and the sign-in is a real server-side OTP with
hashed credentials. That is a better foundation than most side projects reach.

But almost none of that is what stands between you and the stores. **Saṃvara is
not a small app that needs polish — it is a single-tenant appliance that needs to
become a multi-tenant product.** Four things dominate the effort, and everything
else is downstream of them:

1. **There is no concept of a user.** No table has a user column. One hardcoded
   email address may sign in. One person's data is *the* data.
2. **Every charge hits your credit card.** Beeminder charges the owner of the
   token, and there is one token, in server env.
3. **There is no iOS app**, and the approach the Android app takes (a WebView
   around samvara.app) is the single most-rejected app shape on the App Store.
4. **There are no legal or compliance artifacts at all** — and the app collects
   data about sexual behavior, which is special-category data under GDPR and
   raises the bar on everything.

Rough order of magnitude for a competent solo developer: **6–10 months** to a
defensible v1 on both stores, of which maybe six weeks is store paperwork and the
rest is turning an appliance into a product. Cutting scope (see
[Decisions to make first](#decisions-to-make-first)) can pull that in a lot — the
biggest single lever is whether real money is in v1 at all.

---

## What you have today

Worth stating plainly, because a lot of it survives the transition.

**Backend** (`backend/`, ~1,200 lines Python + ~960 lines of tests)

- `ratchet.py` — pure, I/O-free domain logic. Portable as-is.
- `beeminder.py` — a single choke point for money, with a floor, a cap, and a
  dry-run mode.
- `main.py` — every charging path serialized behind one lock, re-checking state
  inside it; charge before persist so a failed charge leaves state untouched;
  idempotent auto-miss; a debounce against double-clicked confirms.
- `auth.py` / `security.py` — OTP with a send cooldown, an attempt cap, and
  SHA-256-only storage of codes and session tokens. Sign-out revokes server-side.
- Tests cover the race interleavings, the "failed charge leaves state untouched"
  invariant for every endpoint, and a ledger-balance check. That test suite is an
  asset; keep it and grow it.

**Frontend** (`frontend/`)

- A single-page app with a considered visual design, dark/light theming, and a
  real API client that degrades sensibly (boot errors, 401 → sign-in gate).
- The build guard that refuses to ship a bundle containing the mock gate or a
  personal address is a nice piece of paranoia.

**Android** (`android/`, ~380 lines Java, zero dependencies)

- A WebView plus a JobScheduler poller that fires staged deadline notifications.
  Deliberately minimal, works on de-Googled devices, and the "site deploy == app
  update" property is real.

**Ops**

- Dockerized, non-root, deployable to Fly or any Docker host; CI runs the money
  tests on every push; a cron tick so deadlines resolve with the app closed.

---

## The four blockers

### 1. Multi-tenancy: the data model has no users

This is not a refactor, it is the central piece of work.

| Where | What |
| --- | --- |
| `backend/app/store.py:39` | `commitments` table is `(id, seq, data)` — no owner |
| `backend/app/store.py:69` | `metric_days` is `(metric, day, count)` — no owner |
| `backend/app/store.py:81` | `penalty_days` is `(day, tz, charged_count)` — no owner |
| `backend/app/store.py:87` | settings is one JSON row in `kv` for the whole server |
| `backend/app/config.py:71` | `AUTH_EMAIL` — *the one* address allowed to sign in |
| `backend/app/main.py:332` | `METRICS` — your five personal metrics, hardcoded |
| `backend/app/main.py:356` | `PENALTY_START_DAY = "2026-07-18"` — hardcoded |
| `backend/app/config.py:83` | `METRICS_TZ` — one timezone for everyone |
| `backend/app/security.py:31` | static `API_TOKEN` grants full access to everything |
| `backend/Dockerfile` | `--workers 1`, required by the process-level locks |

Two users signing in today would see and mutate the same commitments. The work:

- [ ] Add a `users` table (id, email, created_at, tz, status, deleted_at).
- [ ] Add `user_id` to commitments, metric_days, penalty_days; make settings
      per-user rather than a global `kv` row.
- [ ] Scope **every** query by `user_id`. Make the store interface take a user so
      an unscoped query is impossible to write by accident.
- [ ] Sessions already carry an email (`store.get_session`) — turn that into a
      `current_user` dependency and thread it through every route.
- [ ] Replace the `AUTH_EMAIL` allowlist with real signup. Keep an invite/waitlist
      flag if you want a controlled rollout.
- [ ] Make the metric vocabulary user-defined (see
      [the content-category problem](#5-the-content-category-changes-the-rules)).
- [ ] Per-user timezone instead of `METRICS_TZ`.
- [ ] Move off the process-level lock. `asyncio.Lock` + `threading.RLock` only
      work within one process; with users you want Postgres row locks
      (`SELECT … FOR UPDATE` on the commitment) so you can run more than one
      worker. This also removes the `--workers 1` constraint.
- [ ] Replace `/v1/tick` driven by a public GitHub Actions workflow holding a
      god-token. Multi-tenant, the sweep must iterate users and can't be
      authenticated by a static full-access bearer. Move it in-process
      (APScheduler / a worker) or to a scoped, single-purpose credential.
- [ ] `_recent_lapse` (`main.py:225`) is in-memory and lost on restart — move the
      debounce into the database.

**Migrations.** The schema is `CREATE TABLE IF NOT EXISTS` with no versioning
(`store.py:36`). Before you have users you can drop and recreate; after, you
can't. Adopt Alembic (or equivalent) *before* the first external user.

**Database.** SQLite on one Fly volume with no backup story is fine for you and
indefensible for other people's money. Move to managed Postgres with
point-in-time recovery. The store is already behind a narrow interface, which is
exactly what makes this tractable.

### 2. Money: whose card is it?

`backend/app/beeminder.py:71` sends `auth_token=settings.beeminder_token` — one
server-side token. Beeminder charges whoever owns it. **With two users, the
second user's slip charges you.** This is the hardest product decision in the
whole transition, and it determines your store strategy, your legal exposure, and
your business model.

Three options:

**(a) Each user connects their own Beeminder account (OAuth).**
Least new infrastructure — Beeminder keeps handling cards, PCI, and disputes.
Costs: every user must have a Beeminder account and a card on file with them
(brutal signup funnel for a consumer app), you need a registered OAuth client,
you must store per-user tokens encrypted at rest with rotation, and you need
Beeminder's blessing for a third-party app charging their users via their API.
Confirm that with them in writing before building on it.

**(b) You become the merchant (Stripe).**
Users add a card in your app; you charge off-session on a lapse. Best product
experience, and what comparable apps do. Costs: Stripe account and underwriting,
SetupIntent + off-session PaymentIntent with SCA/3DS handling, failed-payment and
retry logic, refunds, chargebacks, receipts, and a clear legal answer to **where
the money goes**. "You keep it" is simple but makes the product feel predatory
and puts you on the hook for revenue recognition and tax. "It goes to charity"
is better marketing and much worse legally — routing other people's money to
third parties can implicate money-transmitter licensing. Get advice before
choosing.

**(c) No money in v1.**
Ship the ratchet, the streaks, the notifications, and the data tracking, with
stakes as a later release. This removes the single biggest source of store risk,
legal risk, and support burden, and it lets you learn whether people want the
product before you learn whether you can charge for it. **This is my
recommendation for v1.**

Whatever you pick, these are required for consumer money:

- [ ] An **aggregate cap per user** — daily, weekly, monthly. `MAX_CHARGE_USD` is
      per charge only (`config.py:60`, and the README says so). One bug or one
      runaway loop currently charges a user unboundedly. This is the difference
      between a bug and a scandal.
- [ ] An immutable `charges` ledger table (user, amount, provider, provider id,
      status, idempotency key), not `totalCharged` accumulated inside a JSON blob
      (`store.py:141`).
- [ ] A pending→committed outbox around the charge. Today, if the charge succeeds
      and the write fails, the user is charged with no record — the current design
      correctly protects the opposite direction but not this one.
- [ ] Client-supplied idempotency keys on every charging endpoint, not just the
      10-second debounce.
- [ ] Per-user dry-run/arming, replacing the global `BEEMINDER_DRYRUN`. Note
      `deploy/fly/fly.toml` commits `BEEMINDER_DRYRUN = "false"` — live charges
      armed by a file in the repo. Fine for one person; not a multi-tenant default.
- [ ] Explicit, revocable consent before any charge is armed, with a visible
      "money is on" state and a global kill switch the user controls.
- [ ] Receipts by email for every charge, and a full charge history in-app.
- [ ] Fix the penalty tap flow: today, five taps on the "goal broken" metric is
      $5 with no confirmation step (`main.py:403`). The deferred end-of-day sweep
      is a thoughtful mitigation for *you*, but a consumer needs an explicit
      confirm and a visible, undoable pending state.

**Store rules on this.** Both stores exempt physical goods and real-world
services from their in-app-purchase requirements; digital content and features
must use IAP (Apple) or Play Billing (Google). A forfeited commitment stake is a
real-world consequence, not digital content, so external payment is the right
lane — but reviewers will not reach that conclusion on their own. Practical
guidance:

- Collect payment methods **on the web**, not in the app, and don't sell anything
  in-app. This is how comparable apps thread it.
- Apple's May 2025 US guideline change permits external-payment links and calls
  to action in the US storefront with no entitlement or commission; other
  storefronts still require IAP or a regional entitlement. If you launch outside
  the US, check the current rules per storefront.
- Write the App Review notes explaining the model *before* you submit, and expect
  at least one rejection round on this point regardless.
- If you later add a **subscription** for the app itself, that *is* digital
  content and *does* require IAP/Play Billing. Plan for it.

### 3. iOS does not exist, and the Android approach won't port

There is no iOS code in the repo. More importantly, the shape of the Android app
doesn't transfer:

- **Apple 4.2 (Minimum Functionality)** is the most common rejection for
  "website in a WebView" apps. `MainActivity.java:38` loads
  `https://samvara.app/` and the UI is entirely that page. Submitted to Apple
  as-is, this gets rejected.
- **Apple 2.5.2** requires apps to be self-contained and not change their
  features by downloading code. The explicit design goal that "every Pages deploy
  updates the app with no reinstall" is in direct tension with that.
- **Google Play's Spam and Minimum Functionality policy** targets the same shape.
  Your native poller and notifications probably clear Google's bar. They would
  not clear Apple's.
- **The 15-minute JobScheduler poller cannot exist on iOS.** iOS has no reliable
  periodic background execution. Deadline alerts must become server-driven push.

So: **one real client rewrite, targeting both platforms.** Options, with my read:

| Approach | Fit |
| --- | --- |
| Native Swift + keep Java Android | Best result, ~2× the client work, two codebases forever |
| **React Native / Expo** | **Recommended.** One rewrite covers both, real native shell satisfies 4.2, mature push/notification/secure-storage story, and your UI is simple enough that the port is mostly mechanical |
| Flutter | Equally viable; pick on your comfort, not on merit |
| Capacitor (wrap the existing HTML) | Fastest, but lands right back in 4.2 territory — it *is* the current app with a different wrapper |

The existing frontend (`frontend/src/app.html`, 1,760 lines of design-tool export
with inline styles and a custom `sc-if` template syntax, packed and unpacked by
Python scripts) is a real maintenance ceiling for a product you intend to iterate
on with onboarding flows, experiments, and multiple contributors. The client
rewrite is the natural moment to leave it behind. Keep the web app — as a
marketing site, an account/billing portal, and the data-deletion URL Google
requires — but the phone apps should stop being a WebView of it.

### 4. Notifications must become server-driven push

Today: the phone polls `/v1/commitments` every ~15 minutes and decides locally
what to fire (`DeadlineJobService.java`). That design has no iOS equivalent, and
on Android it drains battery and scales as *N users × 96 polls/day* against your
API.

- [ ] Device-token registration (APNs + FCM), per user, per device.
- [ ] Move stage logic (due-6h, grace, grace-3h, parked, auth-dead) server-side —
      it already largely exists in the tick sweep.
- [ ] A scheduler that fires per-commitment at the right instant rather than a
      loop over every commitment every 15 minutes. This is the piece that stops
      being trivial as the user count grows.
- [ ] Keep the dedup discipline (at most one notification per stage per rung) —
      that part of the current design is right; move it into the database.
- [ ] Per-user notification preferences and quiet hours, plus honoring OS-level
      permission state. Both stores review notification behavior.

### 5. The content category changes the rules

The Data tab tracks pornography viewing, non-porn sexual content, masturbation,
and "looking at women with sexual desire" (`backend/app/main.py:332-338`). Under
**GDPR this is Article 9 special-category data** (data concerning a person's sex
life). Holding it for other people, rather than yourself, brings:

- [ ] Explicit, granular, separately-recorded consent — not a checkbox buried in
      a ToS.
- [ ] A Data Protection Impact Assessment. For Article 9 data at scale this is
      effectively mandatory, not optional.
- [ ] Encryption at rest, strict access control, and an honest answer to "can the
      operator read it?" (Today: yes, trivially.) Consider whether client-side
      encryption of the metric data is worth it — it is a genuine trust
      differentiator for exactly this category, and it forecloses several classes
      of breach and subpoena risk.
- [ ] Data minimization and retention limits, real deletion (not soft-delete),
      and a documented breach-notification process.
- [ ] An EU representative if you target the EU. Consider **not** launching in the
      EU for v1 — this is a defensible scope cut.
- [ ] Age gating. 18+, given both the money and the content.
- [ ] Store ratings: expect 17+/18+ on Apple and a Mature rating via the IARC
      questionnaire on Play, and disclose sexual-behavior data collection in
      Apple's privacy labels and Play's Data safety form. Under-declaring here is
      a takedown risk, not a paperwork risk.

**Strong recommendation:** make the metric vocabulary **user-defined**. Today it
is a hardcoded list that makes Saṃvara *inherently* a sexual-behavior tracker.
If users author their own metrics, the app is a commitment-and-tracking tool that
some users point at this, which is a materially better position for store review,
for GDPR scope, and for the size of the addressable market. You keep your setup
as a template; you stop shipping your recovery program as everyone's schema.

---

## The rest of the findings

### Security and privacy

- [ ] **The static `API_TOKEN` is a god-token** (`security.py:31`) accepted on
      every endpoint, and it lives in a GitHub Actions secret used by a workflow
      in a public repo. Scope it to the tick, or eliminate it with an in-process
      scheduler.
- [ ] **No rate limiting** beyond the OTP send cooldown, and that cooldown is
      keyed by email, not IP. Add per-IP and per-user limits across the API.
      Signup and OTP endpoints will be abused within days of a public launch.
- [ ] **Session model is thin**: a 30-day bearer token in `localStorage`, no
      refresh, no rotation, no device list, no revoke-all. Add short-lived access
      tokens + refresh, and on mobile store them in Keychain/Keystore rather than
      WebView localStorage (`MainActivity.java:135` harvests the token out of the
      page today).
- [ ] **No account deletion.** Both stores now require it: Apple requires in-app
      account deletion for any app with accounts; Google requires an in-app path
      *and* a publicly reachable web URL. Neither exists.
- [ ] No audit logging of security-relevant events.
- [ ] `addJavascriptInterface` + `setJavaScriptEnabled` is a native bridge exposed
      to page content (`MainActivity.java:76`). Currently only `onTheme`, so the
      risk is low — but it disappears entirely with a native client.
- [ ] No dependency scanning, no secret scanning in CI.
- [ ] Get a third-party security review before launch. You are holding sexual
      behavior data and payment authority for strangers.

### Reliability and operations

- [ ] **No backups.** A lost Fly volume today loses every user's data and the
      entire charge ledger. Managed Postgres with PITR, plus tested restores.
- [ ] **No error tracking** (Sentry or equivalent), **no metrics**, **no
      alerting**. When a charge sweep starts failing at 3am you will find out from
      users.
- [ ] **Single machine, single worker** — no redundancy, and any deploy is
      downtime. Fine at n=1; not for paying strangers.
- [ ] `/v1/health` is a liveness check only; add readiness (DB reachable,
      scheduler alive, payment provider reachable).
- [ ] No staging environment. You need one before you have users, especially with
      money in the loop.
- [ ] A runbook: what to do when charges fail, when the sweep stalls, when a user
      disputes a charge.
- [ ] Support tooling — some way to look up a user and their charge history
      without opening a SQLite file over SSH.

### Web app / frontend

- [ ] **The "Request access" form silently discards submissions**
      (`frontend/src/app.html:1657`) while telling the user *"your message is on
      its way. I'll reply to you soon."* Harmless in a personal build; shipped to
      consumers it is a false statement to every person who fills it in. Wire it
      up or remove it. This one is worth fixing this week regardless of the rest.
- [ ] Real signup, email verification, password/passwordless recovery, and
      account settings.
- [ ] Onboarding that explains the ratchet, the grace window, and — if money ships
      — exactly what will be charged and when, with affirmative consent.
- [ ] Commitment lifecycle gaps: no edit, no delete, no archive, no pause. Users
      will need all four.
- [ ] Per-commitment ratchet rules. `+1 day` / `+$1` are hardcoded
      (`ratchet.py`, `suggestNextRung`), which is your preference, not everyone's.
- [ ] Data export (also a GDPR portability requirement).
- [ ] Accessibility: the export is inline-styled with no ARIA, no focus
      management, and unaudited contrast. Worth a pass before launch.
- [ ] No analytics. You will be flying blind on activation and retention — pick
      something privacy-respecting and disclose it.
- [ ] Localization, eventually. Not v1.
- [ ] A marketing site. `samvara.app` currently *is* the app; you need a public
      page that explains the product, hosts the privacy policy and terms, and
      carries the store badges.

### Android app

- [ ] **No release signing.** `build.gradle` has no `signingConfigs`; the README
      ships a debug-signed APK. Create an upload keystore, enroll in Play App
      Signing, and back the keystore up somewhere you won't lose it.
- [ ] Ship an **`.aab`**, not an APK. Play requires app bundles for new apps.
- [ ] `minifyEnabled false` (`build.gradle:26`) — enable R8 with a ProGuard config
      for release builds.
- [ ] **`android/.gitignore` is broken.** Its entries are written repo-root
      relative (`android/app/build/`) but the file lives in `android/`, so they
      match `android/android/app/build/`. Result: **83 build artifacts and the
      whole `.gradle` cache are committed.** Fix the paths and `git rm -r
      --cached` the artifacts.
- [ ] Hardcoded endpoints: `SITE` (`MainActivity.java:38`) and `DEFAULT_API_BASE`
      (`DeadlineJobService.java:36`). Move to build config with per-flavor values.
- [ ] Store assets: 512×512 icon, feature graphic, phone and tablet screenshots,
      short and full descriptions. Only an adaptive icon exists today.
- [ ] Play Console declarations: Data safety, content rating (IARC), target
      audience, ads, government-app, financial-features (relevant if money ships).
- [ ] Target API level: `targetSdk 35` is current-ish, but Play enforces a rolling
      minimum — check the current requirement at submission time and budget for a
      yearly bump.
- [ ] **Closed testing gate.** Personal developer accounts created after
      13 Nov 2023 must run a closed test with **at least 12 testers for 14
      continuous days** before applying for production access. Testers need real
      devices and real Google accounts, and all 12 must overlap in the same
      unbroken window — if one drops out on day seven, the counter resets. This
      does not apply to organization accounts. **Start recruiting testers early;
      this is a calendar dependency, not an engineering one, and it is the single
      most common cause of "my app is done but I can't ship" on Play.**
      (Registering as an organization instead avoids it — worth considering when
      you decide on a legal entity anyway.)

### iOS app, from zero

- [ ] Apple Developer Program enrollment ($99/yr). An organization enrollment
      needs a D-U-N-S number and takes real calendar time — start early.
- [ ] Client rewrite (see [blocker 3](#3-ios-does-not-exist-and-the-android-approach-wont-port)).
- [ ] APNs setup, certificates, provisioning, bundle ID.
- [ ] Sign in with Apple is **required** if you offer any third-party social
      login. Email OTP alone doesn't trigger it — but if you add "Connect
      Beeminder" as a login path, revisit this.
- [ ] App Store Connect: screenshots at every required size, 1024×1024 icon,
      description, keywords, support URL, marketing URL, privacy policy URL, and
      **privacy nutrition labels**.
- [ ] **A working demo account for App Review.** Impossible today — the
      `AUTH_EMAIL` allowlist admits exactly one address, and review needs a real
      login. Reviewers cannot receive your OTP emails, so plan a review-only
      account with a fixed code or a bypass path.
- [ ] Review notes explaining the money model, the ratchet, and why external
      payment applies. Assume a reviewer with no context and thirty seconds.
- [ ] TestFlight beta before submission.
- [ ] Budget for 2–4 rejection rounds. First submissions of anything involving
      money plus sexual-health content essentially never pass on the first try.

### Legal and business

None of this exists today, and most of it gates submission.

- [ ] **Privacy policy** at a public URL. Required by both stores; must cover
      special-category data, subprocessors (Fly, Resend, Stripe/Beeminder), and
      retention.
- [ ] **Terms of service.** Essential the moment you take money — it is where the
      charge authorization, the refund policy, and the limitation of liability
      live.
- [ ] **Support URL and support email**, both monitored. Required fields.
- [ ] **Account and data deletion URL**, publicly reachable (Play requirement).
- [ ] **A legal entity.** Do not hold strangers' sexual-behavior data and payment
      authority as a natural person. An LLC also opens the door to organization
      accounts on both stores — which, on Play, sidesteps the 12-tester gate.
- [ ] GDPR: lawful basis, DPAs with every subprocessor, the DPIA above, an EU
      representative if you target the EU.
- [ ] CCPA/CPRA if you have California users (you will).
- [ ] COPPA: gate under-13 explicitly. Given money and content, gate under-18.
- [ ] Refund and dispute policy, written before the first dispute.
- [ ] Tax: sales tax / VAT if you sell subscriptions; income treatment of
      forfeited stakes if you keep them.
- [ ] Trademark and name clearance for "Saṃvara" / samvara.app. Also check
      App Store and Play name collisions before you get attached.
- [ ] Insurance (E&O / cyber) once you have real users.

---

## Decisions to make first

These four determine most of the plan. Everything above is much easier to
sequence once they're settled.

**1. Is real money in v1?**
My recommendation: **no**. Ship the ratchet, streaks, tracking, and notifications
first. Money is the largest source of store risk, legal risk, support burden, and
engineering risk simultaneously — and it is the one piece you can add in v2 once
you know people want the product. If money *is* in v1, option (b) Stripe is the
better product and the bigger lift; option (a) Beeminder OAuth is faster but
gates every signup on the user already having a Beeminder account.

**2. Does the app stay a WebView?**
It cannot, for iOS. Recommendation: one React Native rewrite covering both
platforms. Keep the web app as marketing, account portal, and the deletion URL.

**3. Do the metrics stay hardcoded?**
Recommendation: **no** — make them user-defined. This is a modest engineering
change with a large payoff in store risk, GDPR scope, and market size.

**4. Personal or organization developer accounts?**
Recommendation: **organization**, via the LLC you want for liability reasons
anyway. It removes Play's 12-tester/14-day gate and is the right posture for an
app handling this data. Trade-off: D-U-N-S and entity formation take weeks — so
start this first, in parallel with everything else.

---

## Phased plan

Rough effort for one competent full-time developer. Phases 0–2 are largely
parallelizable with the legal track.

### Phase 0 — Foundations (2–4 weeks, mostly not code)

Start now; the calendar items have long lead times.

- Form the legal entity; begin D-U-N-S and developer account enrollment.
- Draft privacy policy and terms with counsel (real counsel — special-category
  data plus money).
- Decide the four questions above.
- Fix the two things that are wrong today regardless of the plan: the
  access-request form that discards submissions, and the broken
  `android/.gitignore` plus committed build artifacts.
- Stand up error tracking and a staging environment.

### Phase 1 — Multi-tenancy (6–10 weeks)

The core of the transition.

- Postgres + Alembic migrations; port the store behind its existing interface.
- `users` table; `user_id` on every table; every query scoped.
- Real signup, verification, recovery; per-user settings and timezone.
- User-defined metrics.
- Replace process-level locks with row-level locking; drop `--workers 1`.
- Move the tick in-process, per-user; retire the god-token.
- Account deletion, end to end.
- Backups with a *tested* restore.
- Extend the test suite to prove per-user isolation as rigorously as it currently
  proves the money invariants.

### Phase 2 — Clients (8–14 weeks)

- React Native app, both platforms, from the existing design.
- APNs + FCM registration; server-side notification scheduling; retire the poller.
- Onboarding flow.
- Secure token storage; short-lived tokens + refresh.
- Commitment edit/delete/archive/pause; per-commitment ratchet rules; data export.
- Accessibility pass.

### Phase 3 — Money, if it's in v1 (4–8 weeks)

- Stripe (or Beeminder OAuth) integration.
- Immutable ledger, idempotency keys, pending→committed outbox.
- Aggregate per-user caps, arming consent, kill switch, receipts, history.
- Confirm-and-undo on the penalty tap flow.
- Extend the money tests to the new provider and the new caps.

### Phase 4 — Store readiness (3–5 weeks, overlapping)

- Release signing, R8, `.aab`; App Store Connect and Play Console setup.
- All store assets and metadata; privacy labels and Data safety; content ratings.
- Review demo account; review notes for the money model.
- Marketing site with policy, terms, support, and deletion URLs.
- **Play closed testing: 12 testers, 14 continuous days** — recruit during
  Phase 2, not Phase 4.
- TestFlight beta.
- Security review.

### Phase 5 — Launch and after

- Staged rollout; support inbox; monitoring and alerting on the money paths;
  incident runbook.
- Then the long tail: localization, subscriptions (which brings IAP/Play Billing
  into scope), EU launch with the GDPR work done properly.

---

## If you only do five things next

1. **Decide whether money is in v1.** Everything else branches off it.
2. **Start the entity and developer-account paperwork.** It is pure calendar time
   and it blocks the end of the project, not the beginning.
3. **Do the multi-tenancy work**, with per-user isolation tested as seriously as
   the money invariants already are.
4. **Commit to one client rewrite** for both platforms; stop investing in the
   WebView shell.
5. **Fix the access-request form** — it currently tells people you'll reply and
   then throws the message away.

---

Sources for the store-policy points, current as of August 2026:

- [Apple App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
- [Apple App Store Review Guideline updates](https://developer.apple.com/news/?id=3ozbk628)
- [Guideline 3.1.1 digital vs. physical goods](https://ptkd.com/journal/guideline-3-1-1-in-app-purchase-digital-goods-rejection-fix)
- [Google Play closed testing: 12 testers, 14 days](https://www.testerscommunity.com/google-play-closed-testing)
- [Google Play 14-day testing rule](https://www.revenuecat.com/blog/engineering/google-play-14-day)

Store policies move quickly — re-verify anything payment-related and any target
API level against the official guidelines at submission time. Nothing here is
legal advice; the GDPR, money-transmission, and tax points in particular need a
lawyer who has seen your actual model.
