# Saṃvara React Native Client

A modern React Native mobile client for Saṃvara, built for iOS and Android with TypeScript, Zustand state management, and React Navigation.

## Overview

This is a React Native rewrite of the Saṃvara web app, providing native mobile experiences while sharing the same backend API. The app allows users to manage commitments, track metrics, and receive deadline notifications.

## Architecture

```
client/
├── src/
│   ├── App.tsx                    # Root app component with navigation
│   ├── navigation/
│   │   ├── AuthStack.tsx          # Auth screens (sign-in, verify, request)
│   │   └── AppStack.tsx           # Main app screens (commitments, metrics, settings)
│   ├── screens/
│   │   ├── auth/                  # Authentication screens
│   │   │   ├── SignInScreen.tsx
│   │   │   ├── VerifyCodeScreen.tsx
│   │   │   └── AccessRequestScreen.tsx
│   │   └── app/                   # App screens (placeholders for further development)
│   │       ├── CommitmentsScreen.tsx
│   │       ├── CommitmentDetailScreen.tsx
│   │       ├── MetricsScreen.tsx
│   │       ├── SettingsScreen.tsx
│   │       ├── NotificationsScreen.tsx
│   │       └── SessionsScreen.tsx
│   ├── services/
│   │   └── apiClient.ts           # Axios-based API client with auto auth
│   ├── store/
│   │   └── authStore.ts           # Zustand auth state management
│   └── types/
│       └── index.ts               # TypeScript type definitions
├── android/                       # Android native code
├── ios/                           # iOS native code
├── package.json                   # Dependencies
├── tsconfig.json                  # TypeScript configuration
├── .babelrc                       # Babel configuration
├── .eslintrc.json                 # ESLint configuration
└── app.json                       # React Native configuration
```

## Tech Stack

- **React Native 0.72+** — Cross-platform mobile framework
- **TypeScript** — Static typing for JavaScript
- **React Navigation 6** — Native navigation for mobile
- **Zustand** — Lightweight state management
- **Axios** — HTTP client for API communication
- **AsyncStorage** — Local persistent storage for tokens

## Setup & Development

### Prerequisites

- Node.js 16+ and npm/yarn
- Xcode 14+ (for iOS)
- Android SDK 32+ and Android Studio (for Android)
- React Native CLI

### Installation

```bash
cd client
npm install
```

### Running on Android

```bash
npm run android
```

Or using Android Studio:
```bash
./android/gradlew -p android assembleDebug
adb install android/app/build/outputs/apk/debug/app-debug.apk
```

### Running on iOS

```bash
npm run ios
```

Or manually:
```bash
cd ios
pod install
cd ..
npx react-native run-ios
```

### Development Server

Start the Metro bundler:
```bash
npm start
```

Then in another terminal:
```bash
npm run android  # or npm run ios
```

## Architecture & Design

### Authentication Flow

1. User enters email on SignInScreen
2. App calls `POST /v1/auth/send-code` via `apiClient`
3. Navigate to VerifyCodeScreen to enter 6-digit code
4. App calls `POST /v1/auth/verify-code`
5. Token stored in AsyncStorage (via `useAuthStore.verifyCode()`)
6. Zustand state updated, navigation switches to AppStack
7. Token automatically attached to all API requests via axios interceptor

### State Management (Zustand)

Auth state is managed in `src/store/authStore.ts`:

```typescript
const { token, email, loading, error, signIn, verifyCode, signOut } = useAuthStore();
```

Benefits:
- Minimal boilerplate vs Redux
- Per-store subscriptions (no excessive re-renders)
- Persists to AsyncStorage automatically
- Type-safe with TypeScript

### API Client

The `apiClient` (src/services/apiClient.ts) handles:
- Base URL configuration (default: `https://samvara-api.fly.dev`)
- Bearer token injection in all requests
- 401 Unauthorized handling (clears token, triggers re-auth)
- Centralized error handling
- Request timeout (15s)

Usage:
```typescript
import { apiClient } from '@services/apiClient';

// Commitments
const commitments = await apiClient.getCommitments();
const commitment = await apiClient.getCommitment(id);

// Notifications
const notifications = await apiClient.getNotifications(unreadOnly);

// Metrics
const metrics = await apiClient.getMetrics();
```

### Navigation

Two main stacks:

**AuthStack** (unauthenticated):
- SignIn → VerifyCode → AppStack (after auth)
- AccessRequest (side flow for no-access users)

**AppStack** (authenticated):
- Bottom tab navigator with three tabs:
  - Commitments (stack) → Commitment Detail
  - Metrics (stack)
  - Settings (stack) → Notifications, Sessions

## API Integration

The client communicates with the Saṃvara backend API. Key endpoints:

### Authentication
- `POST /v1/auth/send-code` — Send OTP
- `POST /v1/auth/verify-code` — Verify OTP and get token
- `POST /v1/auth/sign-out` — Revoke session

### Commitments
- `GET /v1/commitments` — List all commitments
- `GET /v1/commitments/{id}` — Get single commitment
- `POST /v1/commitments` — Create new commitment
- `POST /v1/commitments/{id}/slip` — Report slip (lapse)
- `POST /v1/commitments/{id}/miss` — Report miss
- `POST /v1/commitments/{id}/auto-miss` — Trigger auto-miss
- `POST /v1/commitments/{id}/confirm-clean` — Mark rung clean

### Metrics
- `GET /v1/metrics` — Get all metrics and today's data
- `POST /v1/metrics/{key}/bump` — Increment/decrement metric count

### Notifications
- `GET /v1/notifications` — List notifications (with unread_only filter)
- `GET /v1/notifications/{id}` — Get single notification
- `POST /v1/notifications/{id}/read` — Mark notification as read
- `POST /v1/notifications/read-all` — Mark all as read

### Settings & Security
- `GET /v1/settings` — Get user settings
- `PATCH /v1/settings` — Update user settings
- `GET /v1/sessions` — List active devices
- `DELETE /v1/sessions/{deviceId}` — Revoke specific device
- `DELETE /v1/sessions` — Revoke all sessions

See backend documentation for full API details.

## Build & Deployment

### Debug Build

```bash
# Android
npm run android

# iOS
npm run ios
```

### Release Build

**Android:**
```bash
cd android
./gradlew assembleRelease
# Signed APK at app/build/outputs/apk/release/app-release.apk
```

**iOS:**
```bash
# In Xcode: Product → Scheme → Edit Scheme → Run tab → Build Configuration → Release
# Then Product → Archive
```

## Testing

```bash
npm test
```

## Linting & Type Checking

```bash
npm run lint
npm run type-check
```

## Configuration

### API Base URL

The app defaults to `https://samvara-api.fly.dev`. To override:

1. In the app, go to Settings and enter a custom API base URL
2. The URL is stored in AsyncStorage under `apiBaseUrl`
3. On app restart, the `apiClient` uses the stored URL

For development, set `DEFAULT_API_BASE` in `src/services/apiClient.ts` or use your local server:
```typescript
const DEFAULT_API_BASE = 'http://localhost:8000';  // for local dev
```

## Roadmap & TODO

This is a foundation for the React Native client. Placeholder screens have been created for all main features. Next steps:

- [ ] Implement full CommitmentDetailScreen (display rung, history, actions)
- [ ] Implement MetricsScreen (chart, series data, bump controls)
- [ ] Implement NotificationsScreen (list, mark read, filter)
- [ ] Implement SessionsScreen (list devices, revoke)
- [ ] Add background notification handling (push notifications)
- [ ] Add offline support (local caching, sync on reconnect)
- [ ] Add app-specific theming (dark mode toggle)
- [ ] Add accessibility features (labels, contrast, nav hints)
- [ ] Add analytics (optional; respecting privacy)
- [ ] Performance optimization (memoization, lazy loading)
- [ ] App Store & Play Store submission

## Troubleshooting

### "Execution failed for task ':app:compileDebugJavaWithJavac' (Android)"

```bash
cd android
./gradlew clean
cd ..
npm run android
```

### "No module named 'react-native'" (iOS)

```bash
cd ios
pod install
cd ..
npm run ios
```

### "Metro bundler not responding"

```bash
# Kill all node processes
killall node

# Start bundler again
npm start
```

### "401 Unauthorized" on all API calls

- Token may have expired (30-day session TTL)
- Sign out and sign in again
- Check that AsyncStorage actually stored the token (use React DevTools)

### "Cannot find module '@services/apiClient'"

Check that TypeScript path aliases in `tsconfig.json` match your imports. Should be:
```typescript
import { apiClient } from '@services/apiClient';
```

## Performance Tips

- Use React.memo for complex screens
- Lazy load heavy dependencies
- Use FlatList over ScrollView for long lists (with keyExtractor)
- Profile with React Native Debugger: https://github.com/jhen0409/react-native-debugger
- Measure frame rate with `adb logcat *:S ReactNativeJS:V`

## Security

- Token stored in AsyncStorage (app-private on iOS, encrypted on Android with proper manifest)
- HTTPS enforced for all API calls
- No sensitive data logged in console (uses console.warn/error only for errors)
- Bearer token injected via axios interceptor, never visible in URLs

## License

Same as parent Samvara project.

## Contributing

See parent Samvara contributing guidelines.
