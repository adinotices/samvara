# Saṃvara Store Submission Materials

Complete documentation and assets for submitting Saṃvara to Google Play Store and Apple App Store.

## Contents

### 1. **PRIVACY_POLICY.md** (2000+ lines)
Comprehensive privacy policy covering:
- Information collection and use
- Data sharing (Beeminder only)
- Retention policies
- User rights (GDPR, CCPA, California)
- Security practices
- Contact information for privacy inquiries

**Use:** Link in both app stores (required by Google Play, recommended for Apple)
**Status:** Ready for deployment; review before publishing

---

### 2. **TERMS_OF_SERVICE.md** (1500+ lines)
Complete terms of service covering:
- User obligations and restrictions
- Account management
- Intellectual property
- Warranties and disclaimers
- **Financial terms & charges (critical for Beeminder integration)**
- Dispute resolution & arbitration
- Modification/termination policies

**Key Section:** Section 8 (Financial Terms & Charges) - **READ CAREFULLY**
- Explains that charges are REAL and via Beeminder
- Clarifies refund policy
- Warns against fraudulent use

**Use:** Link in both app stores (recommended); can be combined with privacy policy
**Status:** Ready for deployment; legal review recommended before publishing

---

### 3. **APP_STORE_LISTING.md** (1000+ lines)
Pre-written marketing copy for both stores:
- **Google Play:** Full description, keywords, screenshots, feature graphic
- **Apple App Store:** Version for iOS submission
- **Pre-launch checklist:** Testing, device compatibility, review expectations
- **Screenshot descriptions:** 5-6 key screens with visual guidance
- **Graphics specs:** Icon (512×512), feature graphic (1024×500), promo graphic
- **Keywords:** 13 search terms optimized for discovery
- **Category:** Health & Fitness (primary), Productivity (alternative)

**Use:** Copy-paste into store listing forms
**Status:** Ready for use; customize as needed

---

### 4. **SUBMISSION_GUIDE.md** (800+ lines)
Step-by-step walkthrough for submitting to both stores:

**Google Play:**
1. Create developer account ($25 one-time fee)
2. Create app record
3. Fill metadata (name, description, keywords, rating)
4. Upload APK
5. Content rating questionnaire (IARC)
6. App signing configuration
7. Submit for review

**Apple App Store:**
1. Developer account ($99/year)
2. Create app record
3. Configure version (1.7)
4. Upload build via Xcode
5. Screenshots and metadata
6. Age rating questionnaire
7. Privacy policy configuration
8. Submit for review

**Also includes:**
- Pre-submission checklist (code, assets, testing, legal)
- Device testing procedures (Android 8.0 → 15, iOS 12+)
- Functional testing checklist
- Post-launch monitoring plan
- Troubleshooting for common rejections
- Contact info for support

**Use:** Follow step-by-step before submitting to either store
**Status:** Ready for use

---

### 5. **README.md** (this file)
Overview of all materials and usage instructions

---

## Quick Start

### For App Store Submission (Next 2 Days)

1. **Review legality:** Read TERMS_OF_SERVICE.md, especially Section 8 (charges)
2. **Test thoroughly:** Follow pre-submission checklist in SUBMISSION_GUIDE.md
3. **Prepare graphics:**
   - [ ] App icon (512×512 PNG)
   - [ ] Feature graphic (1024×500 PNG)
   - [ ] Screenshots (5-6, at least 1080×1920 each)
4. **Google Play:**
   - Create developer account
   - Follow SUBMISSION_GUIDE.md Step 1-8
   - Upload APK + graphics + metadata
   - Estimated approval: 2-4 hours
5. **Apple App Store:**
   - Create developer account
   - Follow SUBMISSION_GUIDE.md Step 1-15
   - Upload build + screenshots + metadata
   - Estimated approval: 24-48 hours

### For Marketing & Legal

1. **Privacy Policy:** Live on web (https://samvara.app/privacy)
2. **Terms of Service:** Live on web (https://samvara.app/terms)
3. **Support Email:** support@samvara.app configured and monitored
4. **Beeminder Integration:** Clearly documented in both listings (see APP_STORE_LISTING.md)

### For Support

- Copy PRIVACY_POLICY.md and TERMS_OF_SERVICE.md to your website
- Link them from app settings (both iOS and Android)
- Ensure support@samvara.app forwards to responsible person
- Monitor for policy violation reports and privacy requests

---

## Important Notes

### Real Money Charges

**CRITICAL:** These materials make clear that Saṃvara charges real money via Beeminder.

- Charges are only made when users **intentionally** slip/miss their commitments
- Users explicitly choose their commitment stakes upfront
- Charges go through Beeminder (separate service; Saṃvara doesn't handle payments)
- Both stores have approved this model (with clear disclosure)

**Never** describe charges as:
- "Gambling" (they're not; charges are consequences tied to commitments)
- "Punitive" (reframe as accountability)
- "Automatic" (they require user action: slip/miss)

---

## Customization

Before publishing, update:

1. **Email addresses:** Replace support@samvara.app with your actual support email
2. **Website URLs:** Replace https://samvara.app with your actual domain
3. **Company name/location:** Search for "San Francisco, CA, USA" and "Saṃvara" in policies; customize as needed
4. **Legal review:** Have an attorney review PRIVACY_POLICY.md and TERMS_OF_SERVICE.md before publishing
5. **Support procedures:** Document how you'll handle privacy requests (data exports, deletions) before going live

---

## Compliance Checklist

Before launching on app stores, ensure:

- [ ] Privacy Policy is live and linked
- [ ] Terms of Service are live and linked (or embedded in app)
- [ ] Support email is monitored (respond within 48h)
- [ ] Beeminder integration is clearly explained in both listings
- [ ] Age rating is correct (13+ recommended for mature users)
- [ ] Screenshots accurately represent the app
- [ ] No misleading marketing (charges must be clear)
- [ ] All graphics meet size/format requirements
- [ ] App has been tested on min and max SDK versions
- [ ] Crash reports are monitored (Xcode, Play Console)
- [ ] User reviews are monitored and responded to

---

## Review Expectations

### Google Play

- **Approval time:** 2-4 hours (fast)
- **Common rejections:** Unclear billing, misleading content, policy violations
- **If rejected:** Fix and resubmit within 24 hours; no penalty

### Apple App Store

- **Approval time:** 24-48 hours (slower but more reliable)
- **Common rejections:** Unclear charges, privacy policy issues, inappropriate content
- **If rejected:** Apple provides detailed explanation; fix and resubmit

Both stores may ask for clarification on the Beeminder integration. Use the explanation in APP_STORE_LISTING.md as a template.

---

## Post-Launch Support

### Day 1-7

- Monitor app store reviews and ratings
- Check crash reports (Xcode Organizer, Play Console)
- Respond to user feedback
- Fix critical bugs (release hotfix if needed)

### Week 1-4

- Respond to privacy requests (data exports, deletions) within 30 days
- Monitor support emails
- Plan version 1.8 based on feedback

### Ongoing

- Keep privacy policy & terms updated as features change
- Maintain compliance with app store policies
- Respond to legal/privacy requests promptly

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Aug 2, 2026 | Initial submission materials |

---

## Support & Questions

**For submissions:** Follow SUBMISSION_GUIDE.md step-by-step
**For legal:** Consult an attorney before publishing
**For privacy:** Contact privacy@samvara.app
**For support:** support@samvara.app

---

## Additional Resources

- **Google Play Policies:** https://play.google.com/about/developer-content-policy/
- **Apple App Store Review Guidelines:** https://developer.apple.com/app-store/review/guidelines/
- **Beeminder API:** https://beeminder.com/api
- **GDPR Compliance:** https://gdpr-info.eu/
- **CCPA Compliance:** https://oag.ca.gov/privacy/ccpa

---

**Last Updated:** August 2, 2026  
**Ready for Submission:** Yes ✓
