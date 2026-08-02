# Samvara Android Build & Release Guide

## Overview

The Samvara Android app is a minimal WebView shell that wraps the web UI (`https://samvara.app`) with native deadline notifications. The backend provides the API (`https://samvara-api.fly.dev` by default).

## Prerequisites

- Android SDK 35 (compileSdk)
- Android NDK (optional; not used by this app)
- JDK 17+
- Gradle 8.0+ (managed by `gradlew`)

## Building

### Debug Build (Development)

```bash
./gradlew assembleDebug
```

Outputs: `android/app/build/outputs/apk/debug/app-debug.apk`

Features:
- Debuggable code
- No minification
- Longer build time, larger APK
- Suitable for development and testing

### Release Build (Production)

```bash
./gradlew assembleRelease
```

Outputs: `android/app/build/outputs/apk/release/app-release.apk`

Features:
- Minified and obfuscated code
- Optimized resources (~30% smaller than debug)
- Non-debuggable
- Faster runtime performance
- Must be signed with release keystore for Play Store

## Code Signing

### Setup Release Keystore

```bash
# Generate a new keystore (one-time setup)
keytool -genkey -v -keystore release.keystore \
  -keyalg RSA -keysize 2048 -validity 10000 -alias release
```

### Configure Gradle

Edit `android/app/build.gradle` and uncomment the signing config:

```gradle
signingConfigs {
    release {
        storeFile file('release.keystore')
        storePassword System.getenv('KEYSTORE_PASSWORD')
        keyAlias System.getenv('KEY_ALIAS')
        keyPassword System.getenv('KEY_PASSWORD')
    }
}
```

And in the `release` buildType:

```gradle
buildTypes {
    release {
        ...
        signingConfig signingConfigs.release
    }
}
```

### Build & Sign

Set environment variables and build:

```bash
export KEYSTORE_PASSWORD="your-keystore-password"
export KEY_ALIAS="release"
export KEY_PASSWORD="your-key-password"
./gradlew assembleRelease
```

The signed APK will be at `android/app/build/outputs/apk/release/app-release.apk`.

## Testing

### Local Device/Emulator

```bash
# Install debug build
./gradlew installDebug

# Install release build (if signed)
./gradlew installRelease
```

### Manual Testing Checklist

1. **App Launch**
   - [ ] App opens without crashes
   - [ ] WebView loads `https://samvara.app`
   - [ ] Theme matches system dark/light preference

2. **Authentication**
   - [ ] Can sign in with OTP
   - [ ] Session token persists across app close/reopen
   - [ ] Can sign out

3. **Deadline Notifications**
   - [ ] Background job schedules successfully
   - [ ] Notifications appear for upcoming deadlines
   - [ ] "Last call" (grace < 3h) notification shows
   - [ ] Auto-charged notifications appear when grace expires

4. **Network Conditions**
   - [ ] App handles offline gracefully (no crashes)
   - [ ] Reconnection refetches latest data
   - [ ] 401 Unauthorized triggers "sign-out" notification

5. **Permissions**
   - [ ] Notification permission requested on app launch
   - [ ] App works without `ACCESS_NETWORK_STATE` permission (GrapheneOS)

6. **Performance**
   - [ ] No ANR (Application Not Responding) crashes
   - [ ] Background job completes within timeout
   - [ ] Memory usage stays reasonable

### ProGuard/R8 Validation

To ensure minification doesn't break the app:

```bash
./gradlew clean assembleRelease
# Install and test the release APK thoroughly
./gradlew installRelease
```

Check logs for method not found or class not found errors:

```bash
adb logcat | grep -E "ClassNotFoundException|NoSuchMethodError"
```

If minification breaks the app, add rules to `proguard-rules.pro`.

## Play Store Submission

### Pre-submission

1. Test release build on multiple devices (minSdk 26 to latest)
2. Verify ProGuard/R8 doesn't break WebView or notifications
3. Create app listing with:
   - Screenshots (portrait and landscape)
   - Description
   - Changelog (see `RELEASE_NOTES.md`)
   - Privacy policy link
4. Ensure API server is running and accessible

### Graphics Assets

Required for Play Store:
- **App icon:** 512×512 PNG (JPEG not allowed)
- **Screenshots:** Min 2, max 8 per locale; min 320×569 or 512×854
- **Feature graphic:** 1024×500 PNG (for app store listing)
- **Promo graphic:** 180×120 PNG (optional)

### Submission Steps

1. Upload signed APK (`app-release.apk`)
2. Fill app details (title, description, category)
3. Set content rating questionnaire
4. Choose countries/regions for distribution
5. Set pricing (free or paid)
6. Submit for review

Review typically takes 2-4 hours.

## Troubleshooting

### ProGuard/R8 Breaks the App

Symptom: App crashes with `ClassNotFoundException` or `NoSuchMethodError` in release build.

Solution:
1. Check `adb logcat` for the missing class/method
2. Add a `-keep` rule to `proguard-rules.pro`
3. Rebuild: `./gradlew clean assembleRelease`
4. Re-test

### Signing Issues

Symptom: "Keystore was tampered with" or invalid password.

Solution:
1. Verify environment variables are set correctly
2. Verify keystore file exists
3. Try signing manually to debug:
   ```bash
   jarsigner -verify -verbose android/app/build/outputs/apk/release/app-release.apk
   ```

### WebView Fails to Load

Symptom: Blank screen or "This page can't be reached".

Solution:
1. Ensure device has internet connection
2. Verify API server is running
3. Check API base URL in SharedPreferences (via Android Studio debugger)
4. Verify DNS resolution: `getaddrinfo("samvara.app")`

### Deadline Notifications Don't Appear

Symptom: Deadline Job Service runs but no notifications.

Solution:
1. Check notification permission is granted
2. Verify token is stored in SharedPreferences after sign-in
3. Check `DeadlineJobService.check()` logs:
   ```bash
   adb logcat | grep -E "DeadlineJobService|samvara"
   ```
4. Verify API responds with commitments: `curl -H "Authorization: Bearer $TOKEN" https://samvara-api.fly.dev/v1/commitments`

## Architecture Notes

### Minimal Dependencies

The app uses only framework APIs:
- `android.webkit.*` — WebView rendering
- `android.app.job.*` — Background task scheduling
- `android.app.*` — Notifications
- `org.json.*` — JSON parsing (framework-bundled)
- `java.net.*` — HTTP requests

No third-party dependencies (no gradle dependencies block), which keeps the APK small and reduces supply-chain risk.

### Signing Model

The app harvests the session token from the web app's `localStorage` and uses it to call the API from the background job. The token is stored in `SharedPreferences` (app-private storage, not world-readable).

### Deadline Notification Timing

- Polled every ~15 minutes (JobScheduler minimum interval)
- Notifications deduped in SharedPreferences by `commitment_id|rung|stage`
- Stages: `due6` (6h to deadline), `grace` (past deadline, in grace window), `grace3` (< 3h left), `parked` (auto-charged)

## Files Reference

- `app/build.gradle` — Build config, versioning, signing, ProGuard rules
- `app/src/main/AndroidManifest.xml` — Permissions, activities, services
- `app/src/main/java/app/samvara/shell/MainActivity.java` — WebView shell + session harvest
- `app/src/main/java/app/samvara/shell/DeadlineJobService.java` — Background deadline poller
- `app/proguard-rules.pro` — ProGuard/R8 rules to preserve framework APIs
- `RELEASE_NOTES.md` — Version history and deployment notes
- `BUILD.md` — This file
