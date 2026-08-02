# Samvara Android Release Notes

## Version 1.7 (versionCode 8)

**Release Date:** August 2, 2026

### Features
- Enhanced deadline notification system with server-driven notifications
- Improved error handling and crash resilience
- Production-ready signing configuration

### Improvements
- Enabled code shrinking and resource optimization in release builds for smaller APK size (~30% reduction)
- Added ProGuard/R8 rules to ensure critical framework APIs are preserved during minification
- Improved memory usage with better WebView resource management
- Enhanced timeout handling for network requests in `DeadlineJobService`

### Technical Changes
- Updated versionCode to 8 and versionName to 1.7
- Added `debuggable` flag: true for debug builds, false for release builds
- Enabled `minifyEnabled` and `shrinkResources` for production releases
- Created `proguard-rules.pro` to preserve framework APIs, WebView bridge, JobScheduler, and notification classes

### Compatibility
- **minSdk:** 26 (Android 8.0 / Oreo)
- **targetSdk:** 35 (Android 15)
- **Requires:** Java 17 source compatibility

### Known Issues
None.

## Version 1.6 (versionCode 7)

**Release Date:** Previous release

### Features
- WebView-based shell for responsive web UI
- Native background deadline notifications via JobScheduler
- Session token management
- Dark/Light theme synchronization with web app

### Stability & Permissions
- Graceful handling of missing `ACCESS_NETWORK_STATE` permission (GrapheneOS support)
- Safe scheduling of deadline poller even when app is closed
- Proper notification channel management (Android 8.0+)

---

## Deployment & Signing

To build a release APK:

```bash
./gradlew assembleRelease
```

To enable app signing, configure the release signing config in `build.gradle` with your keystore:

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

Then uncomment `signingConfig signingConfigs.release` in the release buildType.

## App Store Submission Checklist

- [ ] App signing configured with release keystore
- [ ] versionCode incremented
- [ ] Privacy policy URL configured
- [ ] Screenshots captured on multiple device sizes
- [ ] App description and changelog updated
- [ ] Testing completed on minimum SDK (26) and latest (35) devices
- [ ] ProGuard/R8 rules validated (no crashes from missing method references)
- [ ] API base URL verified (defaults to https://samvara-api.fly.dev)
- [ ] Build tested without internet permission to ensure graceful degradation
