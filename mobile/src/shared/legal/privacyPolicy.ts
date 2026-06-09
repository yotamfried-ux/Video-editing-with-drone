export const PRIVACY_POLICY = `
SPORTREEL — PRIVACY POLICY
Last updated: June 2026

1. INTRODUCTION
SportReel ("we", "us", "our") operates the SportReel mobile application. This Privacy Policy explains what data we collect, why we collect it, and how we protect it. We are committed to GDPR compliance (EU 2016/679), Israeli Privacy Protection Law (5741-1981) and its Amendment 13, and applicable App Store privacy requirements.

2. DATA WE COLLECT

2a. Account Data
When you register, we collect your email address and name. This data is required to provide the service. Legal basis: contract performance (GDPR Art. 6(1)(b)).

2b. Face Biometric Data (Optional)
If you choose to enable automatic Reel matching, you may upload a face photo. We use this to compute a facial embedding (a mathematical representation) to match you to your highlight clips. Legal basis: your explicit consent (GDPR Art. 9(2)(a); Israeli Privacy Protection Law Amendment 13).
- You can delete your face data at any time from Profile → Face Recognition → Remove Face Data.
- Face data is never shared with third parties or used for any purpose other than Reel matching.
- Face embeddings are stored encrypted in our database (Supabase, hosted in EU-Central).

2c. Payment Data
Payment transactions are processed by Stripe (for card payments) and Meshulam (for Bit wallet payments). We do not store your card number, CVV, or banking credentials. We store only the transaction ID and amount for your purchase records.

2d. Usage Data
We collect anonymized event data (e.g., "Reel viewed", "checkout started") to improve our service. This data does not contain your identity and is used only for aggregate analytics.

2e. Push Notification Token
If you grant notification permission, we store your device's Expo push token to send you alerts when new Reels featuring you are available. You can disable notifications in your device Settings at any time.

3. HOW WE USE YOUR DATA
- Account Data: to authenticate you, display your purchases, and contact you if necessary.
- Face Data: exclusively to match you with Reels containing your likeness and send notifications.
- Payment Records: to fulfill your purchases and provide download access.
- Usage Analytics: to understand how athletes use the App and improve the experience.
- Push Tokens: to notify you of new personalized Reels.

4. DATA SHARING
We do not sell your data. We share data only with:
- Supabase (database & storage, EU-Central data center) — database processor
- Cloudflare (video streaming, US/EU) — video delivery
- Stripe (card payments, US) — payment processor
- Meshulam (Bit payments, Israel) — payment processor
- Expo (push notifications, US) — notification delivery
Each processor is bound by a Data Processing Agreement and subject to GDPR adequacy or Standard Contractual Clauses where applicable.

5. DATA RETENTION
- Account data: retained until you delete your account.
- Face biometric data: deleted immediately upon your request (Profile → Remove Face Data) or when you delete your account.
- Purchased Reel files: retained on our servers for 7 days post-purchase, then deleted. Your downloaded copy is yours permanently.
- Unpurchased Reels: deleted 48 hours after upload.
- Analytics events: retained for 24 months in aggregated form.

6. YOUR RIGHTS
Under GDPR and Israeli law, you have the right to:
- Access: request a copy of your personal data.
- Rectification: correct inaccurate data.
- Erasure ("right to be forgotten"): delete your account and all associated data.
- Portability: receive your data in a machine-readable format.
- Withdraw consent: for face biometric processing, at any time, without affecting prior processing.
- Object: to processing based on legitimate interests.
To exercise these rights, use the "Contact Support" feature in your Profile screen or email us directly.

7. SECURITY
We use industry-standard measures including:
- TLS encryption for all data in transit
- Encrypted storage for face embeddings
- Private storage buckets (no public access) for photos and videos
- Row-level security on all database tables

8. CHILDREN
The App is not intended for users under 16. We do not knowingly collect data from children under 16.

9. COOKIES
The App does not use browser cookies. We use AsyncStorage (device-local) solely to maintain your login session.

10. CHANGES
We may update this Privacy Policy. If changes materially affect your rights, we will notify you via the App. Continued use of the App after notification constitutes acceptance.

11. CONTACT
Data Controller: SportReel
Contact: Use the "Contact Support" option in your Profile screen.
`.trim();

export const FACE_CONSENT_TEXT =
  'I consent to SportReel collecting and processing my facial biometric data solely to identify me in sports footage and send me relevant notifications. This is optional. I can delete my data at any time from my Profile. My data will not be shared with third parties.';
