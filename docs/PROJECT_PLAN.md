# Saṃvara: end-to-end project plan

Companion to [`APP_STORE_READINESS.md`](./APP_STORE_READINESS.md). That document
says *what needs to be true*. This one says *who does what, in what order*.

## Decisions taken

| | Decision | Answer | Date |
| --- | --- | --- | --- |
| **D-1** | Money in v1? | **Yes — stakes ship in v1** | 2026-08-01 |
| **D-4** | Client framework | **React Native / Expo** | 2026-08-01 |

**Consequences of D-1.** The payments track is in scope, so **D-2** (payment
rail) and **D-3** (where forfeited money goes) move from "answer when reached" to
"answer early" — D-3 in particular gates counsel (P3-2) and can't be designed
around. Plan on ~6–8 months to submission rather than 4–6, and expect the money
model to be the hardest part of App Review. Everything in 1D is now on the
critical path rather than optional, and P3-7 (Stripe underwriting or Beeminder's
written OK) becomes a long-lead item alongside P3-1 through P3-4.

**Consequences of D-4.** 1G proceeds as a React Native port targeting both
platforms. The Android WebView shell is now in maintenance-only mode — no further
investment beyond keeping it working until the RN build replaces it.

---

Split three ways:

- **[Part 1](#part-1--i-can-build-this-now)** — work I can do with no input from you. Correct
  regardless of how you answer anything else.
- **[Part 2](#part-2--i-can-build-this-once-youve-decided)** — work I can do, blocked on a decision only
  you can make. Each item states the question, the options, and my recommendation.
- **[Part 3](#part-3--only-you-can-do-this)** — work that is structurally yours: legal identity,
  accounts, credentials, money, attestations, and anything requiring a signature.

## How to read this

There is one thing that matters more than the ordering of the engineering:
**several Part 3 items have multi-week lead times and block the *end* of the
project, not the beginning.** Entity formation → D-U-N-S → organization developer
account is a serial chain that can eat two months of calendar while I'm writing
code that can't ship without it. Start Part 3 items P3-1 through P3-4 this week,
regardless of where the code is.

The dependency spine:

```
P3 legal/accounts ──────────────────────────────────┐
   (long lead, start now)                           │
                                                    ▼
P2 decisions ──▶ P1 multi-tenancy ──▶ P1 clients ──▶ store submission
   (start now)      (the long pole)      (needs P2-4)
```

Effort figures are rough, in developer-weeks, and assume I'm doing the building.

---

# Part 1 — I can build this now

No decisions needed. Every item here is either required by both stores, required
by the money, or unambiguously correct. Ordered roughly by dependency.

## 1A. Hygiene and honesty (~3 days)

Small, self-contained, worth doing before anything else.

- [ ] **Fix `android/.gitignore`.** Paths are repo-root-relative but the file
      lives in `android/`, so they match `android/android/...`. Fix them and
      `git rm -r --cached` the 83 committed build artifacts and the `.gradle`
      cache.
- [ ] **Fix the access-request form.** `frontend/src/app.html:1657` tells users
      *"your message is on its way"* and then discards it. I'll build a real
      `POST /v1/access-requests` endpoint that persists the request, and make the
      copy true. (Whether it *also* emails you is Part 2 — but persisting it is
      strictly better than today either way.)
- [ ] **Structured logging** throughout the backend, with request IDs.
- [ ] **Error tracking wired** (Sentry SDK, DSN from env — the account is P3-11).
- [ ] **Deepen `/v1/health`**: add a readiness check covering DB reachability and
      scheduler liveness, separate from liveness.
- [ ] **CI additions**: dependency vulnerability scanning, secret scanning, and an
      Android build check so the shell can't silently break.

## 1B. Data layer and multi-tenancy (~6–8 weeks — the long pole)

The core of the transition. Everything else waits on this.

- [ ] **Alembic migrations**, adopted before the first external user exists.
      Today's schema is `CREATE TABLE IF NOT EXISTS` with no versioning
      (`store.py:36`); after you have users, that stops being survivable.
- [ ] **Postgres port** behind the existing `Store` interface. The interface is
      already narrow, which is what makes this tractable. (Provisioning the actual
      database is P3-9.)
- [ ] **`users` table** — id, email, created_at, timezone, status, deleted_at.
- [ ] **`user_id` on every table** — commitments, metric_days, penalty_days — and
      per-user settings replacing the single global `kv` row (`store.py:87`).
- [ ] **Scope every query.** I'll reshape the store interface so it *takes* a user
      and an unscoped query is impossible to write by accident, rather than
      relying on remembering to add a `WHERE`.
- [ ] **`current_user` dependency** threaded through every route. Sessions already
      carry an email (`store.get_session`); this turns that into identity.
- [ ] **Row-level locking** (`SELECT … FOR UPDATE` on the commitment) replacing
      the process-level `asyncio.Lock` + `threading.RLock`. This is what removes
      the `--workers 1` constraint in the Dockerfile and lets you run more than
      one instance.
- [ ] **Move the debounce into the database.** `_recent_lapse` (`main.py:225`) is
      in-memory and lost on restart.
- [ ] **Retire the god-token.** `API_TOKEN` (`security.py:31`) is accepted on
      every endpoint and lives in a GitHub Actions secret in a public repo. The
      tick moves in-process (APScheduler or a worker), iterating users.
- [ ] **Per-user timezone** replacing the global `METRICS_TZ`.
- [ ] **Per-user isolation test suite**, held to the same standard as the existing
      money tests — including the adversarial cases (user A requesting user B's
      commitment id, cross-user metric bumps, cross-user session replay).
- [ ] **Backup tooling and a documented restore drill.** I'll write it; running it
      against real infrastructure is P3-9.

## 1C. Accounts and compliance mechanics (~3–4 weeks)

- [ ] **Real signup** replacing the `AUTH_EMAIL` allowlist (`config.py:71`), with
      email verification and account recovery.
- [ ] **Account deletion, end to end** — in-app path, API, hard delete of all
      user rows, and a public web endpoint. Both stores require this and neither
      exists today.
- [ ] **Data export** (JSON + CSV). GDPR portability, and good product besides.
- [ ] **Session hardening**: short-lived access tokens plus refresh, rotation on
      use, a device list, and revoke-all. Today it's a 30-day bearer in
      `localStorage` with no refresh and no revocation path short of sign-out.
- [ ] **Rate limiting** — per-IP and per-user, across the API. Today the only
      limit is the OTP send cooldown, and it's keyed by email, not IP.
- [ ] **Audit logging** of security-relevant events (sign-in, token issue,
      deletion, charge, settings change).
- [ ] **A review-account path.** App Review needs a working login and reviewers
      can't receive your OTP emails. I'll build a fixed-credential review account
      that's inert on the money paths.
- [ ] **A data inventory document** — every field collected, where it's stored,
      which subprocessors touch it, retention per field. This is what your lawyer
      needs to write a privacy policy from, and handing it to them cuts their time
      (and your bill) substantially. It also feeds Apple's privacy labels and
      Play's Data safety form directly.

## 1D. Money infrastructure (~2–3 weeks)

Correct regardless of which provider you choose, and correct even if money ships
in v2 — you're charging real money *today* with none of it.

- [ ] **Immutable `charges` ledger** — user, amount, provider, provider id,
      status, idempotency key, timestamps. Replaces `totalCharged` accumulated
      inside a JSON blob (`store.py:141`), which is not auditable.
- [ ] **Pending→committed outbox** around each charge. Today's charge-then-persist
      correctly protects against "advanced without charging," but not against
      "charged without recording" if the write fails after the charge lands.
- [ ] **Idempotency keys** on every charging endpoint, replacing reliance on the
      10-second debounce alone.
- [ ] **Aggregate per-user caps** — daily, weekly, monthly. `MAX_CHARGE_USD`
      (`config.py:60`) is per-charge only. (The *mechanism* is Part 1; the
      *numbers* are D-7.)
- [ ] **Per-user arming** replacing the global `BEEMINDER_DRYRUN`, with a visible
      "money is on" state and a user-controlled kill switch. Note
      `deploy/fly/fly.toml` currently commits `BEEMINDER_DRYRUN = "false"` — live
      charges armed by a file in the repo.
- [ ] **Charge receipts by email** and full charge history in-app.
- [ ] **Extend the money test suite** to cover the caps, the ledger, the outbox,
      and per-user isolation of all of it.

## 1E. Notifications (~2–3 weeks)

- [ ] **Device token registration** (APNs + FCM), per user, per device.
- [ ] **Server-side stage logic** — due-6h, grace, grace-3h, parked, auth-dead.
      Most of this already exists in `DeadlineJobService.java`; it moves to the
      server, where it's the only version that can work on iOS.
- [ ] **Per-commitment scheduling** that fires at the right instant, replacing a
      loop over every commitment every 15 minutes. This is the piece that stops
      being trivial as users grow.
- [ ] **Dedup in the database** — one notification per stage per rung. The current
      SharedPreferences approach is right in spirit; it just needs to move.
- [ ] **Retire the polling job.** (Credentials for APNs and FCM are P3-10.)

## 1F. Android release readiness (~1 week)

- [ ] **Release signing config** reading from environment/properties. There are no
      `signingConfigs` today and the README ships a debug-signed APK. (Creating
      and holding the keystore is P3-8 — I must not generate or hold your signing
      key.)
- [ ] **R8 enabled** with a ProGuard config. `minifyEnabled false` today
      (`build.gradle:26`).
- [ ] **`.aab` output** rather than APK; Play requires bundles for new apps.
- [ ] **Move hardcoded endpoints to build config** — `SITE`
      (`MainActivity.java:38`) and `DEFAULT_API_BASE`
      (`DeadlineJobService.java:36`) — with per-flavor values for staging and
      production.
- [ ] **Adaptive icon assets at every density**, plus a splash.

## 1G. Client rewrite (~8–12 weeks — needs D-4 first)

Framework choice is D-4, but everything below is framework-independent work I'll
do once it's answered.

- [ ] Port the existing UI — dashboard, detail, create, decision, lapse, settings,
      data tab — to the chosen framework.
- [ ] Native shells for both platforms, satisfying Apple's 4.2 minimum
      functionality (which the current WebView does not).
- [ ] Secure token storage in Keychain/Keystore, replacing token harvesting out of
      WebView `localStorage` (`MainActivity.java:135`).
- [ ] Push integration on both platforms.
- [ ] Commitment lifecycle: edit, delete, archive, pause. (Pause semantics with
      money at stake is D-8.)
- [ ] Per-commitment ratchet rules, replacing hardcoded `+1 day` / `+$1`.
- [ ] Offline read support and optimistic writes.
- [ ] Accessibility pass — the current export is inline-styled with no ARIA, no
      focus management, and unaudited contrast.
- [ ] Keep the web app alive as marketing site, account portal, and the
      deletion URL Google requires.

## 1H. Store submission materials (~1–2 weeks, drafts only)

I can draft all of these. You review, adjust, and submit them under your account
(P3-14).

- [ ] Store listing copy — short and full descriptions, keywords, what's-new.
- [ ] Screenshot generation at every required device size, from the real app.
- [ ] **App Review notes** explaining the ratchet, the money model, and why
      external payment applies rather than IAP. Assume a reviewer with no context
      and thirty seconds — this is worth more care than it sounds.
- [ ] **Draft answers** for Apple's privacy nutrition labels, Play's Data safety
      form, and the IARC content-rating questionnaire, derived from the data
      inventory in 1C. You must review and attest to these yourself (P3-15);
      under-declaring is a takedown risk, not a paperwork risk.
- [ ] Marketing site structure and scaffold. (Content is D-13.)

---

# Part 2 — I can build this once you've decided

Each item: the question, the options, my recommendation, and what it unblocks.
You can answer these as a numbered list and I'll start.

### D-1. Does real money ship in v1? ⭐ *biggest single decision*

> **ANSWERED 2026-08-01: yes — stakes ship in v1.** The recommendation below is
> kept for the record; the reasoning against it (the stake *is* the mechanism)
> is sound. D-2 and D-3 are now urgent rather than deferrable.

**Recommendation: no.** Ship the ratchet, streaks, tracking, and notifications
first; add stakes in v2.

Money is simultaneously the largest source of store risk, legal risk, support
burden, and engineering risk — and it's the one component you can defer without
gutting the product. Deferring it removes the payments track, most of the store
payment ambiguity, chargeback handling, and a meaningful slice of the legal work,
and it lets you learn whether people want the product before you learn whether
you can charge them.

The counter-argument is real and you should weigh it: the money *is* the
mechanism. A commitment app without a stake is a to-do list, and you may find
retention collapses without it. If you believe that, ship it — just know you're
choosing the longest path.

*Unblocks:* the entire payments track (D-2, D-3, D-7), and roughly 4–8 weeks of
Part 1D beyond the ledger.

### D-2. If money ships: which payment rail?

| Option | Trade-off |
| --- | --- |
| **Beeminder OAuth per user** | Least new infrastructure; Beeminder keeps cards, PCI, disputes. But every user must already have a Beeminder account with a card on file — a brutal consumer funnel — and you need Beeminder's written OK for a third-party app charging their users via their API (P3-7). |
| **Stripe, you as merchant** | Best product experience, what comparable apps do. Costs: underwriting, SetupIntent + off-session PaymentIntent with SCA/3DS, retries, refunds, chargebacks, receipts. |

**Recommendation: Stripe**, if money ships at all. The Beeminder path optimizes
for your build time at the cost of your signup funnel, which is the wrong trade
for a consumer product.

### D-3. If money ships: where does the money go?

You keep it / it goes to charity / it stays with Beeminder.

This is more legal than technical. "You keep it" is simplest but makes the
product feel predatory and puts you on the hook for revenue recognition and tax.
"Charity" markets far better and is much worse legally — routing other people's
money to third parties can implicate money-transmitter licensing. **Get counsel
on this specific question (P3-2) before I build anything that assumes an answer.**

### D-4. Client framework? ⭐ *blocks the largest chunk of work*

> **ANSWERED 2026-08-01: React Native / Expo.** 1G proceeds as an RN port for
> both platforms. The Android WebView shell is maintenance-only from here.

React Native/Expo · Flutter · native Swift + keep Java Android · Capacitor.

**Recommendation: React Native.** One rewrite covers both platforms, the native
shell satisfies Apple's 4.2, the push and secure-storage story is mature, and
your UI is simple enough that the port is mostly mechanical. Flutter is equally
defensible — pick on your comfort, not on merit. Native is the best result at
roughly double the client work and two codebases forever. **Capacitor I'd rule
out**: it's the current app in a different wrapper, which lands right back in
4.2 rejection territory.

*Unblocks:* all of 1G, ~8–12 weeks.

### D-5. Do metrics become user-defined?

**Recommendation: yes.** Today they're your five, hardcoded (`main.py:332`), with
a hardcoded `PENALTY_START_DAY`. That makes Saṃvara *inherently* a
sexual-behavior tracker. If users author their own, it becomes a
commitment-and-tracking tool that some users point at this — materially better for
store review, smaller GDPR surface, and a much larger market. You keep your setup
as a starter template.

### D-6. What happens to your existing data?

Migrate your current commitments and tally history in as user #1, or start the
multi-tenant database clean and keep the old one as an archive?

**Recommendation: migrate you in as user #1.** It exercises the migration path
for real, and you keep your streak. I'll write the migration either way.

### D-7. Aggregate cap values?

Per-user daily, weekly, and monthly ceilings. I need numbers. **Suggested
starting point: $25/day, $100/week, $250/month**, user-adjustable downward but
not upward without a cooling-off period.

### D-8. Pause semantics with money at stake?

If a user pauses a commitment mid-rung, what happens to the deadline and the
stake? Options: pause freezes the clock and disarms the charge; pause is
disallowed on an active rung; pause requires forfeiting the current rung.

**Recommendation: freeze and disarm, with a cooldown** (e.g. one pause per rung,
max 7 days) so it can't be used to dodge every deadline. This is a product-design
question about how much escape hatch you want the ratchet to have — genuinely
yours.

### D-9. Do the ratchet defaults stay `+1 day` / `+$1`?

Currently hardcoded. Once rules are per-commitment (1G), these become defaults.
**Recommendation: keep as defaults**, expose per-commitment overrides, and cap
the escalation so a long streak of slips can't compound into a number that
surprises someone.

### D-10. EU launch in v1?

**Recommendation: no.** Excluding the EU from v1 defers the DPIA, the EU
representative, and a meaningful chunk of Article 9 compliance work, without
costing much market at launch. Revisit once the product is proven. This is a
scope cut, not a shortcut — you still do the GDPR work, just later.

### D-11. Client-side encryption of the metric data?

Genuine trust differentiator for exactly this data category, and it forecloses
whole classes of breach and subpoena risk. Costs: complexity, no server-side
analytics on that data, and painful key recovery — lose the key, lose the data.

**Recommendation: not in v1**, but design the schema so it's addable without a
migration. If you later position on privacy, this is the feature that backs the
claim.

### D-12. Does the name stay "Saṃvara"?

Worth raising deliberately. The `ṃ` is already a known problem in your own
codebase — no font subset carries a precomposed U+1E43, which is why the wordmark
draws it as a CSS dot. That same problem recurs in store listings, in search, and
in anyone trying to type the name to find you. Options: keep it, keep it with
"Samvara" as the store name, or rename.

**Recommendation: keep the brand, use plain "Samvara" everywhere a system will
index or a person will type it.** Also run a trademark and store-collision check
(P3-13) before you get more attached.

### D-13. Launch posture, pricing, and copy

A cluster I can build but can't decide:

- **Business model** — free, subscription, one-time. Note that a subscription
  *is* digital content and does require IAP and Play Billing, which changes the
  compliance picture from D-1's answer.
- **Invite gate or open signup** at launch?
- **Onboarding copy and tone** — especially how you explain the money and the
  grace window. Given the subject matter, this needs your voice, not mine.
- **Marketing site content.**
- **Notification defaults** and quiet hours.
- **Analytics vendor** (and whether you want any).
- **Deletion grace period** — immediate hard delete, or 30-day recovery window?
- **Age gate** — I'd hard-gate 18+ given money plus content. Confirm.

---

# Part 3 — Only you can do this

Structurally yours: identity, signatures, credentials, money, and attestations.
I can guide, draft, and prepare — I cannot be you.

**Sorted by lead time. The first four block the end of the project; start them
this week.**

### Long lead — start immediately

- [ ] **P3-1. Form the legal entity.** *(1–4 weeks)* Do not hold strangers'
      sexual-behavior data and payment authority as a natural person. Also opens
      organization developer accounts, which on Play sidesteps the 12-tester gate
      (P3-6).
- [ ] **P3-2. Retain counsel.** *(ongoing; start now)* Privacy policy, terms of
      service, the DPIA, and specifically D-3 (where forfeited money goes) and
      money-transmission exposure. Hand them the data inventory from 1C — it will
      cut their time significantly. **I can draft structure and supply every
      factual input; I cannot give you legal advice or produce a policy you should
      rely on.**
- [ ] **P3-3. Get a D-U-N-S number.** *(1–5 weeks, free from D&B)* Required for
      organization enrollment in the Apple Developer Program. Requires P3-1 first.
      This is the step that most often silently adds a month.
- [ ] **P3-4. Enroll in both developer programs.** *(1–4 weeks)* Apple Developer
      Program ($99/yr, needs P3-3 for org); Google Play Console ($25 one-time).
      Enroll as the organization, not personally.

### Infrastructure and credentials

- [ ] **P3-5. Business banking and accounting.** Bank account, bookkeeping, and an
      accountant for sales tax/VAT if you sell subscriptions and for the treatment
      of forfeited stakes if you keep them.
- [ ] **P3-6. Recruit 12 beta testers** *(if you end up on a personal Play
      account)*. At least 12 testers on real devices with real Google accounts, all
      overlapping in one unbroken 14-day window — if one drops out on day seven,
      the counter resets. This is calendar time, not engineering time, and it's the
      most common cause of "the app is done but I can't ship it." Recruit during
      the client build, not after. **Organization accounts are exempt** — one more
      reason for P3-1.
- [ ] **P3-7. Payment provider setup** *(if D-1 is yes)*. Stripe account and
      underwriting — identity verification, bank details, business description — or,
      on the Beeminder path, register an OAuth client **and get their written
      confirmation** that a third-party app may charge their users via the API.
      Don't build on that assumption unconfirmed.
- [ ] **P3-8. Create and back up the Android upload keystore.** You generate it,
      you hold it, you back it up somewhere you will still have in five years, and
      you enroll in Play App Signing. **I must not generate or hold your signing
      key** — I'll wire the build to read it from your environment.
- [ ] **P3-9. Provision infrastructure.** Managed Postgres with point-in-time
      recovery, production and staging environments, and a *tested* restore. I'll
      write the configs and the runbook; the accounts and the credit card are
      yours.
- [ ] **P3-10. Push credentials.** APNs key in the Apple developer portal; a
      Firebase project and FCM credentials for Android.
- [ ] **P3-11. Third-party service accounts.** Sentry, your analytics choice
      (D-13), and a paid Resend tier — the free tier will not survive consumer
      signup volume.
- [ ] **P3-12. Domain and email authentication.** DNS, plus SPF, DKIM, and DMARC
      for the sending domain. Get this right before launch: OTP emails landing in
      spam is a silent, total conversion failure that looks like "nobody wants the
      product."

### Diligence and launch

- [ ] **P3-13. Trademark and name clearance.** Search the trademark register, the
      App Store, and Play for collisions on "Saṃvara"/"Samvara" (see D-12).
- [ ] **P3-14. Submit to both stores.** Under your accounts, your identity.
      I prepare every asset (1H); you press the button.
- [ ] **P3-15. Complete and attest to the store declarations.** Apple's privacy
      labels, Play's Data safety form, the IARC content rating. I'll draft each
      from the data inventory — **you must verify and attest, because the
      declaration is a legal statement by you about your app.** Given the data
      category, under-declaring here is a takedown risk.
- [ ] **P3-16. Commission a third-party security review.** You're holding sexual-
      behavior data and, potentially, payment authority for strangers. Budget for
      a real firm, before launch, not after.
- [ ] **P3-17. Insurance.** E&O and cyber, once you have real users.
- [ ] **P3-18. Set up and monitor a support inbox.** Both stores require a support
      URL and a monitored address. Someone has to actually read it — that person
      is you.
- [ ] **P3-19. Run the beta.** TestFlight and Play closed testing, recruiting
      testers, triaging their feedback.
- [ ] **P3-20. Launch, pricing, marketing, and ongoing operations.** Including
      chargeback and dispute response if money ships, and periodic backup-restore
      drills.

---

# How the three parts interleave

```
Month   1     2     3     4     5     6     7     8
        │     │     │     │     │     │     │     │
P3  ████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░████████   entity→DUNS→accounts, then
        ↑ start NOW                          ↑ submit    credentials as needed

P2  ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   D-1/D-4 now; rest as reached

P1     ███ 1A
        ████████████████ 1B multi-tenancy
                    ██████████ 1C accounts
                    ██████ 1D money infra
                              ████████ 1E notifications
                              ████████████████████ 1G clients
                                                ███ 1F android
                                                  ██████ 1H materials
```

Roughly **6–8 months** to submission with money in v1, **4–6** without. The
critical path runs through 1B → 1G, with P3-1→P3-4 running underneath the whole
thing and needing to finish before 1H matters.

---

# What I'd do this week

**You (30 minutes of decisions, then paperwork):**

1. Answer **D-1** (money in v1?) and **D-4** (client framework). Those two unblock
   the majority of Part 1 — everything else can be answered as I reach it.
2. Start **P3-1** (entity) and **P3-3** (D-U-N-S). Pure calendar time; every day
   you wait is a day added to the end of the project.

**Me, immediately, needing nothing from you:**

3. All of **1A** — the `.gitignore` fix, the access-request form that currently
   lies to users, structured logging, health checks, CI scanning.
4. Begin **1B** — Alembic, the users table, and the store-interface reshape that
   makes unscoped queries unwritable.

Say the word on D-1 and D-4 and I'll start on 1A today.
