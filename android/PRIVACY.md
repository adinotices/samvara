# Samvara Android Privacy Policy

## Data Collection & Handling

### Session Token Storage

The app stores your API session token in **app-private SharedPreferences** (encrypted by Android KeyStore on devices with secure storage, accessible only to this app). The token is harvested from the web app's localStorage after you sign in.

**What we collect:**
- Session token (used to authenticate API requests)
- API base URL (configurable per user in Settings)
- Deadline notification history (which notifications have been shown)

**Where it goes:**
- Stored locally in `SharedPreferences` at `data/data/app.samvara.shell/shared_prefs/samvara.xml`
- Sent to the API server (`https://samvara-api.fly.dev` by default) on every deadline poll (~15 minutes)

**How long we keep it:**
- Local storage: Until you sign out or uninstall the app
- Server storage: 30 days (session token expiration, per auth.py)

### Network Security

The app enforces HTTPS for all production servers via `network_security_config.xml`:
- **Production API:** HTTPS only
- **Web app:** HTTPS only (https://samvara.app)
- **Local development:** HTTP allowed only for localhost (127.0.0.1)

### Permissions Requested

1. **INTERNET** — Access to API server and web app
2. **ACCESS_NETWORK_STATE** — Check network connectivity before polling (gracefully disabled on GrapheneOS)
3. **POST_NOTIFICATIONS** — Show deadline notifications (Android 13+; user must grant in system Settings)
4. **RECEIVE_BOOT_COMPLETED** — Reschedule deadline poller after device restart (survives phone restarts)

All permissions are functional (no unused permissions).

### Notification Deduplication

The app dedupes notifications locally using SharedPreferences keys:
- `{commitment_id}|{rung}|{stage}` to track which notifications have been shown
- Stages: `due6` (6h to deadline), `grace` (in grace window), `grace3` (< 3h), `parked` (auto-charged), `auth` (signed out)

This is stored locally and never sent to the server.

### Crash & Error Logs

The app does **NOT** send crash reports or error logs automatically. If the app crashes, debugging requires:
1. Manual installation of a debug build
2. Running `adb logcat` to capture logs
3. Sharing logs voluntarily

Logs are held only in device memory (not persisted after reboot).

### Third-Party Services

- **Web app:** Hosted at https://samvara.app (see web app privacy policy)
- **API server:** Hosted at https://samvara-api.fly.dev (see API privacy policy)
- **No analytics, tracking, or third-party SDKs** in the native Android app

### Data Deletion

To delete your data:
1. Sign out of the app
2. Uninstall the app (removes all local data)
3. Contact support@samvara.app to request server-side deletion (within 30 days your session expires automatically)

### Changes to This Policy

This policy applies to version 1.7+ of the Samvara Android app. Future versions may update this policy with in-app notice.

---

## Play Store Compliance Notes

### Permissions Justification

Per Google Play Policy, each permission must be functionally justified:

| Permission | Justification |
|-----------|---------------|
| INTERNET | Fetch commitments from API; load web UI |
| ACCESS_NETWORK_STATE | Check connectivity before API poll; graceful offline handling |
| POST_NOTIFICATIONS | Show deadline reminders (without notifications, app is useless) |
| RECEIVE_BOOT_COMPLETED | Ensure deadline poller survives reboots (core feature) |

No permission is used for undisclosed purposes.

### Data Safety Form

For Play Store "Data safety" section:

**Data Collected:**
- [ ] Authentication data (session token) — Collected, Encrypted in transit
- [ ] Activity data (which notifications shown) — Collected, Not shared

**Data Sharing:**
- [ ] None. Data is not sold or shared with third parties.

**Security:**
- [ ] App uses HTTPS for all network traffic
- [ ] Session token encrypted in transit (TLS 1.3+)
- [ ] SharedPreferences encrypted by Android KeyStore where available

**Deletion:**
- [ ] User can delete data by uninstalling the app
- [ ] Server-side deletion via support@samvara.app

---

## Questions?

Contact: support@samvara.app

See also:
- Web app privacy policy: https://samvara.app/privacy (or in-app disclosure)
- Android security best practices: https://developer.android.com/training/articles/security-best-practices
