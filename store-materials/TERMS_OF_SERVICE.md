# Terms of Service for Saṃvara

**Effective Date:** August 2, 2026  
**Last Updated:** August 2, 2026

## 1. Acceptance of Terms

By accessing and using Saṃvara (the "Service"), you agree to be bound by these Terms of Service ("Terms"). If you do not agree to these Terms, do not use the Service.

These Terms apply to:
- The Saṃvara website (https://samvara.app)
- The Saṃvara mobile apps (iOS and Android)
- The Saṃvara API

Collectively, these are referred to as the "Service."

## 2. Description of Service

Saṃvara is an accountability platform that allows users to:
- Create personal commitments with time frames and financial stakes
- Track daily progress on commitments
- Record lapses/misses and face financial consequences
- Track personal metrics (habits, behaviors)
- Receive deadline notifications
- Manage security (active sessions, audit logs)
- Export personal data

**Important:** Saṃvara charges real money directly to your payment method on file when you fail to keep your commitments. Charges are processed by Stripe, our payment processor, and the funds are retained by Saṃvara as the accountability consequence you agreed to. See Section 8 below.

## 3. Eligibility

By using Saṃvara, you represent and warrant that:
- You are at least 13 years old (or older in your jurisdiction)
- You are not under any court order prohibiting you from using similar services
- You have the legal capacity to enter into this agreement
- You are not using the Service for any illegal purpose
- If you are under 18, you have permission from your parent/guardian to use Saṃvara

We reserve the right to refuse service to anyone who violates these conditions.

## 4. User Accounts

### 4.1 Account Creation

To use Saṃvara, you must:
- Provide a valid email address
- Verify the email via OTP (one-time passcode)
- Accept these Terms and our Privacy Policy

Accounts are personal and non-transferable. You are responsible for maintaining confidentiality of your session token.

### 4.2 Your Responsibilities

You are responsible for:
- All activity on your account
- Keeping your session token confidential
- Notifying us immediately if your account is compromised (email: support@samvara.app)
- All charges made through your account

If you share your session token or email with others, they can access and modify your account. Use the "Active Sessions" feature to revoke access from specific devices.

### 4.3 Account Termination

You may delete your account at any time via the app (Settings → [Delete Account]). We will:
- Delete all commitments, metrics, and settings within 30 days
- Retain audit logs for 1 additional year (for legal compliance)
- Retain charges history for tax/legal purposes (indefinitely)

Upon termination:
- All future commitments are cancelled
- No new charges will be made
- You lose access to your data (unless previously exported)
- You can still export data before deletion

## 5. Use Restrictions

You agree NOT to:

- **Violate Laws** — Use the Service for any illegal purpose or in violation of local/national/international law
- **Hacking** — Attempt to hack, crack, or exploit the Service or its servers
- **Abuse API** — Make excessive API requests (>1000 req/min without authorization) or reverse-engineer our systems
- **Scraping** — Scrape, crawl, or automate access without permission
- **Harassment** — Use Saṃvara to harass, threaten, or abuse other users (though we don't have multi-user features)
- **Spam** — Send unsolicited messages or advertisements
- **Fraud** — Provide false information, impersonate others, or commit fraud
- **Payment Manipulation** — Intentionally game the system to avoid charges (e.g., stolen card numbers, chargeback abuse) or exploit the billing integration
- **Malware** — Upload viruses, malware, or any malicious code
- **Copyright Violation** — Infringe on third-party copyrights, trademarks, or intellectual property

## 6. Intellectual Property

### 6.1 Our IP

All content on Saṃvara (design, code, text, logos, trademarks) is owned by Saṃvara or its licensors. You retain no intellectual property rights to any Saṃvara-provided content. Except as expressly permitted, you may not reproduce, distribute, or transmit any content without our consent.

### 6.2 Your IP

Any feedback, suggestions, or ideas you provide to Saṃvara become our property, and we may use them without obligation to you.

### 6.3 Open Source

Saṃvara's backend is open-source (see https://github.com/adinotices/samvara). Our open-source code is governed by its respective license (typically MIT or Apache 2.0). For open-source components, that license applies instead of this section.

## 7. Disclaimers

### 7.1 "As-Is" Service

Saṃvara is provided "as-is" and "as-available" without warranties. We make no guarantees that:
- The Service is error-free
- The Service is secure or free from data loss
- Notifications will arrive on time
- Your data will be recoverable after deletion

### 7.2 Third-Party Services

Saṃvara uses Stripe (https://stripe.com) to process payments. We are not responsible for:
- Stripe's processing delays or outages
- Stripe's terms of service or privacy practices
- Data loss on Stripe's servers
- Disputes between you and your card issuer or bank

### 7.3 Limitation of Liability

**To the maximum extent permitted by law:**

We are NOT liable for:
- Indirect, incidental, special, or consequential damages
- Lost profits, revenue, or data
- Damage to your device or any third-party device
- Charges made through the Service (even if erroneous), beyond the refund process in Section 8.3
- Unauthorized access to your account
- Any damages exceeding $100

This limitation applies even if Saṃvara has been advised of the possibility of such damages.

## 8. Financial Terms & Charges

### 8.1 Real Money Charges

**IMPORTANT: Saṃvara is not a game or simulation. Charges are REAL, and Saṃvara — not a third party — is the merchant of record and recipient of the funds.**

When you:
- **Slip** (self-reported lapse) — You are charged the current rung's stake
- **Miss** (deadline passes without response) — You are charged the current rung's stake
- **Fail to recommit** (after a charge) — Future commitments can have higher stakes

Charges are billed directly to the payment method you add in the app, processed through Stripe (https://stripe.com), our payment processor. Saṃvara retains the charged amount as the accountability consequence you agreed to when you set the stake — this money does not go to any other user, charity, or third party unless we explicitly say otherwise for a specific feature.

### 8.2 Payment Method

You add and manage your payment method (credit or debit card) directly in the app, via Stripe's secure card-collection flow. Saṃvara never receives or stores your raw card number — Stripe tokenizes it and Saṃvara only holds a reference (a Stripe Customer ID and payment method token) needed to charge you when a commitment is slipped or missed. You can update or remove your saved card in Settings at any time; removing it without adding a replacement means future slip/miss charges will fail, and unresolved commitments will show as unable to charge until a valid payment method is on file.

### 8.3 Refunds

Charges are generally non-refundable unless:
- The charge was erroneous (duplicate, wrong amount, a bug on our end, etc.) — Contact us at support@samvara.app

We will investigate disputes within 30 days. If a charge was erroneous, we will issue a refund via Stripe, which typically appears on your statement within 5-10 business days.

### 8.4 Disputed Charges

If you dispute a charge, contact **Saṃvara Support** (support@samvara.app) first — since Saṃvara is the merchant of record, we're the ones who can investigate and, where warranted, refund a charge. If you file a chargeback with your card issuer instead of contacting us, we reserve the right to suspend your account while the dispute is resolved, consistent with Stripe's and card networks' dispute-handling requirements.

### 8.5 No Refund for Reneged Commitments

If you create a commitment, then immediately slip/miss to charge yourself (and then request a refund), we will:
1. Deny the refund (you intentionally reneged)
2. Mark your account as fraudulent
3. Potentially ban your account

Saṃvara is built on trust. Don't abuse it.

## 9. Limitation of Warranties

**Saṃvara is provided "as-is" without any warranty, express or implied.**

We do not warrant that:
- The Service will be uninterrupted or error-free
- Results obtained from the Service will be accurate
- Your data will be secure or permanently retained
- Notifications will arrive on time
- The Service will meet your expectations

## 10. Indemnification

You agree to indemnify and hold harmless Saṃvara, its officers, directors, employees, and agents from any claims, damages, losses, or expenses (including attorney fees) arising from:
- Your use of the Service
- Your violation of these Terms
- Your violation of any law
- Your commitments and charges
- Your disputes with your card issuer or bank

## 11. Dispute Resolution

### 11.1 Governing Law

These Terms are governed by the laws of California, USA, without regard to its conflicts of law principles.

### 11.2 Arbitration

**Any dispute, claim, or controversy** arising from these Terms or your use of Saṃvara shall be resolved by binding arbitration, NOT by court.

- **Arbitrator:** A neutral third party arbitrator (JAMS or AAA)
- **Location:** San Francisco, California, USA
- **Language:** English
- **Costs:** Saṃvara covers arbitrator fees; you cover your own attorney fees

### 11.3 No Class Actions

**You waive the right to participate in any class action lawsuit, class arbitration, or representative action.** Any arbitration is one-on-one between you and Saṃvara.

### 11.4 Exception: Small Claims Court

You may pursue a claim in small claims court (if your jurisdiction permits) without using arbitration.

### 11.5 Informal Dispute Resolution

Before arbitration, contact us at support@samvara.app. We will attempt to resolve disputes informally. If unresolved after 30 days, either party may initiate arbitration.

## 12. Modifications to Terms

We may modify these Terms at any time. We will notify you of material changes by:
1. Posting the updated Terms on our website
2. Updating the "Last Updated" date
3. Requiring your acceptance of new Terms before continued use

Your continued use after changes constitutes acceptance of the modified Terms.

## 13. Suspension & Termination

### 13.1 We May Suspend/Terminate Your Account If:

- You violate these Terms
- You engage in fraudulent activity
- You abuse the Service (excessive API requests, etc.)
- You attempt to hack or exploit Saṃvara
- You violate applicable law
- Legal authorities request removal

### 13.2 Upon Suspension/Termination:

- Your account access is immediately revoked
- No new charges will be made
- You lose access to your data (cannot be recovered)
- You may request data export before termination

## 14. Contact & Support

**Questions? Issues? Concerns?**

Email: **support@samvara.app**  
Response time: Within 48 business hours

Website: **https://samvara.app**  
Privacy Policy: **https://samvara.app/privacy**  

## 15. Entire Agreement

These Terms, together with our Privacy Policy, constitute the entire agreement between you and Saṃvara. Any prior agreements are superseded. If any provision is found invalid, the remaining provisions continue in effect.

---

**By using Saṃvara, you acknowledge that you have read, understood, and agree to be bound by these Terms of Service.**

**Last Revised:** August 2, 2026
