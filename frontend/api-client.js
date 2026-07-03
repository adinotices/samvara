// ─────────────────────────────────────────────────────────────────────────────
// Samvara · api-client (REAL)
//
// Drop-in replacement for the bundled reference mock. The UI imports this module
// and calls the exact same exports; nothing in the compiled app changes.
//
//   • The async functions below talk to the backend over fetch().
//   • suggestNextRung / GRACE_MS / graceEnd stay PURE and SYNCHRONOUS — the UI
//     calls them inline inside setState(), so they must not return Promises.
//
// Where the backend lives is resolved at call time in this order:
//   1. localStorage 'samvara.apiBaseUrl'  (set from the in-app Settings screen)
//   2. window.SAMVARA_CONFIG.apiBaseUrl   (from config.js, per environment)
//   3. same origin as the page            (fallback)
// The bearer token, if any, comes from localStorage 'samvara.apiToken' then
// window.SAMVARA_CONFIG.apiToken.
// ─────────────────────────────────────────────────────────────────────────────

const HOUR = 60 * 60 * 1000;

// Must match GRACE_HOURS on the server (24h). The UI uses these two directly and
// synchronously to draw grace countdowns and decide when to call autoMiss.
export const GRACE_MS = 24 * HOUR;
export function graceEnd(rung) { return Date.parse(rung.due) + GRACE_MS; }

// Pure escalation suggestion: one day longer. Kept identical to the server so
// both agree on the default next rung.
export function suggestNextRung(days) { return days + 1; }

// ── config resolution ────────────────────────────────────────────────────────
const LS_BASE = 'samvara.apiBaseUrl';
const LS_TOKEN = 'samvara.apiToken';

function cfg() {
  return (typeof window !== 'undefined' && window.SAMVARA_CONFIG) || {};
}
function ls(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}

// The resolved API root with any trailing '/v1' or slash removed, so both
// "https://host" and "https://host/v1" entered in Settings work identically.
function apiRoot() {
  let base = ls(LS_BASE) || cfg().apiBaseUrl || '';
  base = String(base).trim().replace(/\/+$/, '');       // drop trailing slashes
  base = base.replace(/\/v1$/, '');                      // drop a trailing /v1
  return base;                                           // '' → same-origin
}

function token() {
  return ls(LS_TOKEN) || cfg().apiToken || '';
}

// Exposed for any code that reads it; resolved once at load for display only.
export const API_BASE_URL = (apiRoot() || '') + '/v1';

// ── fetch core ───────────────────────────────────────────────────────────────
async function req(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  const t = token();
  if (t) headers['Authorization'] = 'Bearer ' + t;

  const res = await fetch(apiRoot() + '/v1' + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail || detail; } catch (e) {}
    throw new Error(`Samvara API ${method} ${path} → ${res.status}: ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ── init: best-effort reachability check (never throws on its own) ───────────
export async function init() {
  try { await req('GET', '/health'); } catch (e) { /* surfaced later by refresh */ }
}

// ── reads ────────────────────────────────────────────────────────────────────
export async function listCommitments() { return req('GET', '/commitments'); }
export async function getCommitment(id) { return req('GET', '/commitments/' + encodeURIComponent(id)); }
export async function getSettings() { return req('GET', '/settings'); }

// ── writes ───────────────────────────────────────────────────────────────────
export async function createCommitment({ name, base_days, base_stake }) {
  return req('POST', '/commitments', { name, base_days, base_stake });
}

export async function confirmClean(id) {
  return req('POST', '/commitments/' + encodeURIComponent(id) + '/confirm-clean');
}

export async function chooseNextRung(id, { days, stake }) {
  return req('POST', '/commitments/' + encodeURIComponent(id) + '/choose-next', { days, stake });
}

// { dryRun } returns a preview { charged, recommit:{days,stake}, dryRun } and
// moves no money. A live call charges the stake, then recommits (same length,
// +$1 by default). Explicit { days, stake } override the recommit rung.
export async function reportSlip(id, { dryRun = false, raise = true, days = null, stake = null } = {}) {
  return req('POST', '/commitments/' + encodeURIComponent(id) + '/slip',
    { dryRun, raise, days, stake });
}

export async function reportMiss(id, { dryRun = false, raise = true, days = null, stake = null } = {}) {
  return req('POST', '/commitments/' + encodeURIComponent(id) + '/miss',
    { dryRun, raise, days, stake });
}

// Grace expired with no response: charge + park awaiting recommit. Idempotent
// server-side, so calling it on an already-resolved commitment is harmless.
export async function autoMiss(id) {
  return req('POST', '/commitments/' + encodeURIComponent(id) + '/auto-miss');
}

// The Settings screen edits apiBaseUrl. Persist it as a LOCAL override so this
// client immediately re-points at the new server (the base URL can't be fetched
// from a server you're trying to change). Other fields are patched server-side.
export async function updateSettings(patch) {
  if (patch && typeof patch.apiBaseUrl === 'string') {
    try {
      const v = patch.apiBaseUrl.trim();
      if (v) localStorage.setItem(LS_BASE, v);
      else localStorage.removeItem(LS_BASE);
    } catch (e) { /* localStorage unavailable — non-fatal */ }
  }
  return req('PATCH', '/settings', patch);
}
