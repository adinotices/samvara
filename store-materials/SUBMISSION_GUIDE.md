# Saṃvara App Store Submission Guide

**Last Updated:** August 2, 2026

This guide walks through submitting Saṃvara to Google Play Store and Apple App Store, along with testing and launch procedures.

## Pre-Submission Checklist

### Code & Build

- [ ] Version bumped (Android: versionCode 8, versionName "1.7"; iOS: Version 1.7, Build 8)
- [ ] Changelog updated (see RELEASE_NOTES.md)
- [ ] All tests passing (`npm test` or platform-specific tests)
- [ ] No console.log or console.warn left in production code
- [ ] ProGuard/R8 rules configured (Android)
- [ ] Code signed with release certificate (both platforms)
- [ ] Minification enabled for release build (Android)
- [ ] Symbol upload configured (iOS)
- [ ] Bitcode enabled for iOS (if submitting via App Store Connect)

### Privacy & Legal

- [ ] Privacy Policy finalized (see PRIVACY_POLICY.md)
- [ ] Terms of Service finalized (see TERMS_OF_SERVICE.md)
- [ ] Privacy Policy URL live and accessible
- [ ] Terms URL live and accessible (or link to GitHub)
- [ ] Support email configured (support@samvara.app)
- [ ] Beeminder integration clearly explained (both in-app and in listings)
- [ ] Content rating questionnaire completed (IARC for Google Play)

### Assets

- [ ] App icon (512×512 PNG for Google Play; various sizes for iOS)
- [ ] Feature graphic (1024×500 PNG for Google Play)
- [ ] Promo graphic (180×120 PNG for Google Play; optional)
- [ ] Screenshots (at least 2, up to 8; min 320×569 or larger)
  - [ ] Sign-in screen
  - [ ] Commitments list
  - [ ] Commitment detail
  - [ ] Metrics dashboard
  - [ ] Settings/Security
- [ ] Marketing text (170 chars max for App Store promotional text)
- [ ] Metadata review (descriptions, keywords, categories)

### Device Testing

- [ ] **Android:**
  - [ ] Tested on minSdk 26 (Android 8.0 / Oreo) device or emulator
  - [ ] Tested on latest SDK (Android 15) device or emulator
  - [ ] Tested in both portrait and landscape orientations
  - [ ] Network connectivity tested (WiFi, cellular, offline)
  - [ ] Notification permissions tested
  - [ ] Device tracking (sessions) tested

- [ ] **iOS:**
  - [ ] Tested on iPhone (various sizes: SE, 12, 14 Pro, 15 Pro Max)
  - [ ] Tested on latest iOS version
  - [ ] Tested in both orientations
  - [ ] Tested with VPN (for international users)
  - [ ] Notification permissions tested
  - [ ] HomeKit/Siri intents tested (if applicable)

### Functional Testing

- [ ] Sign-in with email (new account)
- [ ] Verify OTP code
- [ ] Create commitment
- [ ] Confirm clean daily
- [ ] Slip/Miss and verify charge
- [ ] Recommit at higher stake
- [ ] Track metrics (bump/decrement)
- [ ] Review audit log
- [ ] Export user data (GDPR compliance)
- [ ] List active sessions
- [ ] Revoke individual device
- [ ] Revoke all sessions (sign out everywhere)
- [ ] Sign out and sign back in
- [ ] Delete account
- [ ] Request access (if invite-only)

---

## Google Play Store Submission

### Step 1: Create Developer Account

1. Go to https://play.google.com/console
2. Create a developer account (one-time $25 fee)
3. Set up payment information
4. Review and accept Google Play Developer Program Policies

### Step 2: Create Application

1. In Play Console, click "Create app"
2. Enter app name: **Saṃvara**
3. Select category: **Health & Fitness** (or **Productivity**)
4. Confirm default language: **English**
5. Indicate if app is free or paid: **Free** (with in-app Beeminder charges)

### Step 3: Fill Out Store Listing

1. Navigate to **All apps → Saṃvara → Store presence → Main store listing**

2. **App name:** Saṃvara (max 50 chars) ✓
3. **Short description:** "Accountability done right..." (max 80 chars) ✓
4. **Full description:** [See APP_STORE_LISTING.md] (max 4000 chars) ✓
5. **App category:** Health & Fitness ✓
6. **Content rating:** Submit IARC questionnaire
   - Violence: None
   - Profanity: Mild (user-generated)
   - Sexual content: None
   - Gambling: None (real charges ≠ gambling)
   - Alcohol/Tobacco: None
   - **Age Rating: 13+**

7. **Keywords:** [See APP_STORE_LISTING.md] ✓
8. **Feature graphic (1024×500 PNG):** Upload ✓
9. **Screenshots (at least 2, up to 8):** Upload 5-6 screenshots ✓
   - All screenshots should be 1080×1920 or similar aspect ratio
   - Include preview text on each (e.g., "Sign In", "Track Commitments")
10. **Preview video:** Optional (skip for now)
11. **Email address:** support@samvara.app ✓
12. **Website:** https://samvara.app ✓
13. **Privacy policy:** https://samvara.app/privacy ✓
14. **Terms of service:** https://samvara.app/terms ✓

### Step 4: Upload APK

1. Navigate to **Release → Production**
2. Click **Create new release**
3. Upload signed release APK
   - Built with: `./gradlew assembleRelease`
   - Signed with release keystore
   - ProGuard/R8 enabled
4. Add release notes (see RELEASE_NOTES.md)
5. **Set rollout to 100%** (full release, not staged)

### Step 5: Content Rating Questionnaire

1. Navigate to **Content rating → Questionnaire**
2. Select category: **Applications**
3. Answer all questions (you should have answered most during Step 3)
4. Submit questionnaire
5. Review content rating (should be PEGI 13 / USK 12 / similar)

### Step 6: Set Up App Signing

1. Navigate to **Release → App signing**
2. **Option A (Recommended):** Use Google Play App Signing
   - Upload your signing key (keep backup)
   - Google manages the play key for you
3. **Option B:** Self-sign APKs
   - Manage your own key (ensure backups exist)

### Step 7: Review Compliance & Testing

1. Ensure your app complies with Google Play Policies:
   - No malware or dangerous behavior
   - Appropriate content rating
   - Clear data usage disclosure
   - Working links to Privacy Policy & Terms
2. Your app will undergo automated + manual review (typically 2-4 hours)

### Step 8: Submit for Review

1. Navigate to **Release → Production**
2. Review all metadata and screenshots
3. Click **Review and publish**
4. Google will send you an email when review is complete

### Step 9: Post-Launch

Once approved:
- App is live on Google Play Store
- Check reviews daily (respond to feedback)
- Monitor crash reports in Play Console
- Update release notes with new features
- Plan next version (1.8, etc.)

---

## Apple App Store Submission

### Step 1: Developer Account Setup

1. Go to https://developer.apple.com
2. Enroll in Apple Developer Program ($99/year)
3. Accept latest agreements
4. Create App ID (Bundle ID: `app.samvara.shell` or similar)

### Step 2: Create App Record

1. Log into **App Store Connect** (https://appstoreconnect.apple.com)
2. Click **Apps**
3. Click **+** to create new app
4. Select **New App**
5. Fill in:
   - **Name:** Saṃvara
   - **Bundle ID:** app.samvara.shell (or your chosen ID)
   - **Primary language:** English
   - **SKU:** com.samvara.app (unique identifier)
6. Create app

### Step 3: Fill Out App Information

1. Navigate to your app's **App Information** page
2. Set **Category:** Health & Fitness (or Lifestyle)
3. Set **Subcategory:** (optional)
4. Verify **Bundle ID** is correct

### Step 4: Configure Version

1. Navigate to **Versions** → **Create new version**
2. Select **iOS** as platform
3. Enter **Version:** 1.7
4. **Build:** (you'll upload this in Step 6)

### Step 5: Fill Out Metadata

1. **App Name:** Saṃvara
2. **Subtitle:** Accountability Reimagined
3. **Description:** [See APP_STORE_LISTING.md]
4. **Keywords:** [See APP_STORE_LISTING.md] (comma-separated)
5. **Promotional Text:** [See APP_STORE_LISTING.md]
6. **Support URL:** https://samvara.app/support
7. **Privacy Policy URL:** https://samvara.app/privacy
8. **Custom Terms of Service URL:** https://samvara.app/terms (or leave blank if in Privacy Policy)

### Step 6: Prepare Build for Upload

1. In Xcode, select **Product → Scheme → Edit Scheme**
2. Set **Build Configuration** to **Release**
3. Build: **Product → Archive**
4. In Organizer, select archive and click **Distribute App**
5. Select **App Store Connect**
6. Select **Upload**
7. Follow prompts to sign and upload

Alternatively, use Xcode Cloud for automated builds.

### Step 7: Upload Screenshots & Assets

1. Navigate to **Versions → [Your Version] → Screenshots**
2. Upload 5-6 screenshots for each device type:
   - iPhone 6.1" (standard size)
   - iPhone 6.5" (larger size)
   - iPad (optional but recommended)
3. Each screenshot should be:
   - **Resolution:** 1179×2556 px (iPhone 6.1"), 1284×2778 px (6.5"), etc.
   - **Format:** PNG or JPG
   - **Preview text:** Add text overlay (e.g., "Track Commitments")

### Step 8: App Preview & Screen Sets

1. **App Preview (optional):** Upload 15–30 second video of app in action
2. **Preview sets:** Group screenshots by language/region

### Step 9: App Clips (if applicable)

Skip (not applicable for Saṃvara)

### Step 10: Content Rating

1. Navigate to **App Information → Age Rating**
2. Fill out **Age Rating Questionnaire:**
   - Unrestricted Web Access: No
   - Alcohol, Tobacco, Drugs: No
   - Gambling: No (explain real charges are tied to user commitments, not gambling)
   - Medical/Health Info: Yes (users track personal metrics)
   - Violence: No
   - Profanity/Sexual Content: Mild
   - Horror/Scary Themes: No
   - Prolonged Graphic Violence: No
   - Cartoon or Fantasy Violence: No
3. Save and confirm **Age Rating: 4+** (or **12+** if content deemed more mature)

### Step 11: Review Information

1. Navigate to **Versions → [Your Version] → App Review Information**
2. **Notes for App Review:** Explain Beeminder integration and real charges
   - Example: "This app integrates with Beeminder, a quantified self service. Users create accountability commitments with financial stakes (real money). When users fail to keep their commitments, they are charged via Beeminder (user consent on first use). Users can view their charges in the app and manage account settings."
3. **App Review Contact Info:** support@samvara.app
4. **Demo Account (if required):** Provide test email / password (optional)
5. **Sign-in Requirements:** Select "Yes, my app requires sign-in" if applicable

### Step 12: Pricing & Availability

1. Navigate to **Pricing and Availability**
2. Set **Pricing Tier:** Free (in-app Beeminder charges are separate)
3. Set **Territories:** Select all countries where Beeminder operates (most countries)
4. Click **Save**

### Step 13: Privacy Policy

1. Navigate to **App Privacy → Privacy Policy**
2. **Provide privacy policy URL:** https://samvara.app/privacy
3. **Data collection:** Select the types of data you collect:
   - [ ] Health & Fitness
   - [ ] Financial Info (if applicable)
   - [ ] User IDs
   - [ ] Email address
   - [ ] Device ID
   - [ ] Device search history
   - [x] Any other data users input
4. **Data usage:** Indicate your data practices match your privacy policy
5. Submit

### Step 14: Submit for Review

1. Navigate to **Versions → [Your Version]**
2. Review all metadata and screenshots
3. Click **Save** (left sidebar)
4. Scroll up and click **Submit for Review**
5. Apple will send you an email when review is complete (typically 24-48 hours)

### Step 15: Post-Launch

Once approved:
- App is live on App Store
- Monitor ratings and reviews (respond to feedback)
- Enable **Automatic Updates** for bug fixes
- Plan next version (1.8, etc.)

---

## Post-Launch Monitoring

### Daily (First Week)

- [ ] Monitor crash reports (Xcode → Organizer, or App Store Connect → Crashes)
- [ ] Read user reviews (respond to positive & constructive feedback)
- [ ] Check support email (support@samvara.app) for issues

### Weekly

- [ ] Analyze download/install numbers
- [ ] Monitor app rating trend
- [ ] Check for frequent bugs or feature requests
- [ ] Plan bug fix release if critical issues found

### Monthly

- [ ] Release notes for next version
- [ ] Plan new features based on feedback
- [ ] Update store listings if needed

---

## Marketing & Launch Timeline

### 1 Week Before Launch

- [ ] Blog post: "Saṃvara is Coming to the App Store"
- [ ] Email to early beta users
- [ ] Reddit posts in r/accountability, r/quantifiedself, r/productivity (organic)
- [ ] Social media teaser (Twitter, etc., if account exists)

### Launch Day

- [ ] Announce on blog, email, social media
- [ ] Monitor reviews and crash reports closely
- [ ] Respond to user feedback

### 1 Month After Launch

- [ ] Blog post: "Saṃvara Reached [X] Downloads"
- [ ] Thank early users in email newsletter
- [ ] Plan version 1.8 with community feedback

---

## App Store Policies (Critical Points)

### Google Play Policies

1. **Real Money Charges:** Be transparent about Beeminder integration and charges
2. **Privacy:** Link to working privacy policy (required)
3. **Terms:** Recommend providing terms (not required but best practice)
4. **No Malware:** App must not contain viruses or exploit devices
5. **Appropriate Content:** No explicit sexual content (users track habits, but app UI is clean)

### Apple App Store Policies

1. **Guideline 3.1: Payments:** Clearly disclose when real money will be charged
   - In Saṃvara's case, charges happen via Beeminder (external service), so disclose clearly
2. **Guideline 5.1: Legal:** Provide privacy policy (required)
3. **Guideline 5.2: Terms:** Provide terms of service (recommended)
4. **Guideline 2.3: Objectionable Content:** Avoid sexual content or excessive profanity
   - Saṃvara is clean; user-generated commitment names might include words like "porn" (descriptive, not offensive)
5. **Guideline 4.3: Health & Safety:** If tracking health metrics, be careful with medical claims
   - Saṃvara is habit tracking, not medical advice (so OK)

---

## Troubleshooting

### Google Play Rejection: "Unclear billing information"

**Solution:** Add note to app description: "This app integrates with Beeminder, a quantified self service. Users may incur charges via Beeminder based on their commitment settings."

### Apple App Store Rejection: "Real money charges not clearly disclosed"

**Solution:** In App Review Information notes, explain: "This app integrates with Beeminder. Users create accountability commitments with optional financial stakes. Users are charged via Beeminder when they fail to keep their commitments. All charges require explicit user consent and are clearly displayed in the app."

### Build Upload Fails: "Invalid certificate"

**Solution:** Ensure:
- Certificate is not expired
- Certificate matches Bundle ID
- Provisioning profile is up to date
- Rebuild and re-sign

### App Crashes on Launch (Android)

**Solution:** Check logcat:
```bash
adb logcat | grep -E "FATAL|Exception|Error"
```

Common issues:
- Missing ProGuard/R8 rules (add to proguard-rules.pro)
- Hardcoded URL (should be configurable)
- Missing native library

### App Crashes on Launch (iOS)

**Solution:** Check device console in Xcode or Organizer:
1. Xcode → Window → Devices & Simulators
2. Select device
3. View Logs
4. Look for app crashes

Common issues:
- Framework not linked
- Invalid Info.plist
- ARC/memory issues

---

## Contacts & Resources

**Support Email:** support@samvara.app  
**Website:** https://samvara.app  
**GitHub:** https://github.com/adinotices/samvara  

**Google Play Support:**
- Help: https://support.google.com/googleplay/android-developer
- Policies: https://play.google.com/about/developer-content-policy/

**Apple App Store Support:**
- Help: https://developer.apple.com/support/
- Policies: https://developer.apple.com/app-store/review/guidelines/

**Beeminder Integration:**
- API Docs: https://beeminder.com/api
- Support: support@beeminder.com

---

**Version:** 1.0  
**Next Review:** August 15, 2026 (post-launch)
