# Privacy Policy for Saṃvara

**Effective Date:** August 2, 2026  
**Last Updated:** August 2, 2026

Saṃvara ("we," "us," "our," or "Company") operates the Saṃvara mobile application and website (collectively, the "Service"). This Privacy Policy explains how we collect, use, disclose, and safeguard information when you use our Service.

## 1. Information We Collect

### 1.1 Information You Provide Directly

- **Email Address** — Used for account creation and authentication (OTP-based sign-in)
- **Commitments** — Personal accountability commitments you create (goal name, days, stakes)
- **Metrics Data** — Daily tracking data for your personal metrics
- **Settings** — Your API base URL preferences and notification settings
- **Profile Information** — Your timezone preference for deadline calculations

### 1.2 Information Collected Automatically

- **Device Information** — Device name, user agent string, IP address (for security and device tracking)
- **Session Data** — Session tokens (hashed on server, never stored in plaintext)
- **Audit Logs** — Records of sign-ins, sign-outs, and security events with timestamps
- **Usage Analytics** — Count of commitments, metrics tracked, actions taken
- **Notification History** — Which notifications have been shown to you

### 1.3 Information NOT Collected

- We do NOT store your raw card number, CVV, or full payment details ourselves — Stripe, our payment processor, collects and tokenizes your card directly; we only hold a reference (a Stripe Customer ID and payment method token) needed to charge you for a slip/miss
- We do NOT collect location data
- We do NOT use third-party analytics SDKs
- We do NOT track you across other apps or websites
- We do NOT require camera, microphone, or photo library access

## 2. How We Use Information

We use collected information to:

- **Authenticate You** — Verify your identity via OTP and manage your session
- **Provide the Service** — Display your commitments, metrics, and notifications
- **Calculate Deadlines** — Determine when commitments are due based on your timezone
- **Process Charges** — Bill your saved payment method for lapses/misses (via Stripe)
- **Improve Security** — Track active devices, detect unauthorized access, log audit events
- **Comply with Law** — Retain audit logs for regulatory compliance (GDPR, etc.)
- **Support & Debugging** — Respond to support requests and debug technical issues
- **Prevent Abuse** — Detect and prevent unauthorized access or misuse

We do NOT use your information to:
- Sell or share data with advertisers
- Build profiles for targeted advertising
- Share with third parties (except Stripe for payment processing, as described)
- Train machine learning models on your data

## 3. Data Sharing

### 3.1 Payment Processing (Stripe)

When you add a payment method or record a lapse/miss on a commitment, we share the following with Stripe, our payment processor, to add your card and execute the charge:
- Your email address (to create a Stripe Customer record)
- Your card details (collected directly by Stripe's SDK — Saṃvara's servers never see or store your raw card number)
- Charge amount and a brief description (e.g., commitment name, lapse/miss)

Stripe's privacy policy applies to their handling of this data: https://stripe.com/privacy

### 3.2 Other Sharing

We do NOT share your data with other third parties. We do not share with:
- Social media platforms
- Advertisers or marketing partners
- Data brokers or analytics firms
- Government (except as required by law with proper legal process)

### 3.3 Aggregated/De-identified Data

We may analyze aggregated, de-identified usage statistics internally for product improvement (e.g., "X% of users have multiple commitments"). This data cannot identify you.

## 4. Data Retention

- **Session Tokens** — Expire and are deleted after 30 days of inactivity
- **Commitments & Metrics** — Retained indefinitely (or until you request deletion)
- **Audit Logs** — Retained for 1 year for security and compliance purposes
- **Device Records** — Retained until you revoke the device or delete your account

Upon account deletion:
- All commitments, metrics, and settings are deleted within 30 days
- Audit logs are retained for 1 additional year (for security)
- You can request full data export before deletion

## 5. Security

We employ industry-standard security measures:

- **HTTPS/TLS** — All data in transit is encrypted with TLS 1.3+
- **Hashed Tokens** — Session tokens are hashed with SHA-256; plaintext tokens are never stored
- **App-Private Storage** — Sensitive data on your device is stored in app-private directories (not accessible to other apps)
- **Row-Level Locking** — Database transactions use row-level locks to prevent race conditions on charges
- **Access Control** — Only authenticated users can access their own data (no cross-user data leaks)

However, no security system is impenetrable. We cannot guarantee absolute security. If you believe your account has been compromised, please contact us immediately.

## 6. Your Rights & Controls

Depending on your location, you may have rights to:

### 6.1 Access & Portability (GDPR Article 15 & CCPA)

- **Request your data** — Contact us to request a complete export of your personal data
- **Portable format** — Data is provided in JSON format suitable for import to other systems
- **Endpoint** — `GET /v1/data-export` exports all your data in a portable format

### 6.2 Deletion (GDPR Article 17 & CCPA)

- **Delete your account** — Remove all commitments, metrics, and settings
- **Endpoint** — `DELETE /v1/account` removes your account and associated data
- **Audit logs** — Retained for 1 year after deletion (for compliance)

### 6.3 Withdrawal of Consent

- **Sign out** — `POST /v1/auth/sign-out` revokes your current session
- **Revoke all sessions** — `DELETE /v1/sessions` signs you out on all devices
- **Stop notifications** — Turn off notifications in app Settings

### 6.4 Opt-Out Options

- **Notifications** — Disable in app Settings (notifications are on-device; we don't send push notifications)
- **Device tracking** — Revoke devices in Settings → Active Sessions
- **Analytics** — We don't use analytics SDKs, so there is nothing to opt out of

## 7. Children's Privacy

Saṃvara is not intended for users under 13 (or the age of digital consent in your jurisdiction). We do not knowingly collect information from children. If we learn we've collected data from a child, we will delete it immediately.

## 8. California Privacy Rights (CCPA)

If you are a California resident, you have the right to:

- **Know** — What personal information is collected and how it's used
- **Delete** — Request deletion of personal information (see Section 6.2)
- **Opt-Out** — Opt out of "selling" personal information (we do not sell data)
- **Non-Discrimination** — We do not discriminate against you for exercising your rights

To exercise these rights, contact us at: privacy@samvara.app

## 9. European Privacy Rights (GDPR)

If you are in the European Union, you have the rights outlined in Sections 6.1–6.3, plus:

- **Right to Rectification** — Correct inaccurate personal data (via app Settings)
- **Right to Restrict Processing** — Limit how we process your data
- **Right to Object** — Object to processing for specific purposes
- **Data Protection Authority** — File a complaint with your local DPA

Our data processing is based on:
- **Contractual Necessity** — Data processing required to provide the Service (commitments, charging)
- **Legitimate Interests** — Security, fraud prevention, audit logging
- **Consent** — For optional features (notifications, device tracking)

To exercise GDPR rights, contact us at: gdpr@samvara.app

## 10. International Data Transfers

Saṃvara operates servers in the United States. If you access Saṃvara from outside the US, your data is transferred to and stored in the US. By using Saṃvara, you consent to this transfer. We implement Standard Contractual Clauses to provide adequate safeguards for EU/UK residents.

## 11. Third-Party Links

Saṃvara may link to third-party websites (e.g., Stripe, support pages). We are not responsible for their privacy practices. Review their privacy policies before sharing information.

## 12. Policy Changes

We may update this Privacy Policy from time to time. We will notify you of material changes by:
1. Posting the updated policy on our website
2. Updating the "Last Updated" date
3. Requiring re-consent for material changes (via in-app notification or email)

Your continued use of Saṃvara after changes constitutes acceptance of the updated policy.

## 13. Contact Us

**Privacy Questions?** Contact our Privacy Officer:

Email: privacy@samvara.app  
Mail: Saṃvara Privacy Team  
&nbsp;&nbsp;&nbsp;&nbsp;San Francisco, CA, USA

**Response Time:** We aim to respond within 30 days (required by GDPR for data requests).

**Data Protection Authority:** If you believe we've mishandled your data, you have the right to file a complaint with:
- California: California Attorney General
- EU/UK: Your local Data Protection Authority (see https://edpb.ec.europa.eu/about-edpb/board/members_en)

---

**Version:** 1.0  
**Governed by:** Laws of California, USA (arbitration required; no class actions)
