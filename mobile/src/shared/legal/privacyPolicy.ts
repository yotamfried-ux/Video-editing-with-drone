export const PRIVACY_POLICY = `
SPORTREEL — PRIVACY POLICY
Last updated: July 2026

1. INTRODUCTION
SportReel ("we", "us", "our") operates the SportReel mobile application. This Privacy Policy explains what data we collect, why we collect it, and how we protect it. We are committed to applicable privacy law and App Store privacy requirements.

SportReel does not collect face photos, create facial embeddings, or identify an app account from a face in sports footage. Computer vision used by the production pipeline is limited to locating and tracking the featured athlete inside the footage being edited; it is not used for biometric account matching.

2. DATA WE COLLECT

2a. Account Data
When you register, we collect your email address and name. This data is required to provide the service and maintain your account.

2b. Payment Data
Payment transactions are processed by supported payment providers such as Stripe. We do not store your card number, CVV, or banking credentials. We store transaction identifiers, purchase status, amount, and the Reel associated with the purchase where required to provide access.

2c. Usage Data
We collect limited event data such as Reel viewed, checkout started, and payment completed to operate and improve the service. Where practical, analytics are aggregated and are not used to identify a person from their appearance.

2d. Push Notification Token
If you grant notification permission, we may store your device's Expo push token to send service, purchase, delivery, or support updates. You can disable notifications in your device settings at any time.

2e. Sports Footage and Generated Reels
Operators upload sports footage for processing. The production pipeline may detect and track people within that footage to keep one featured athlete continuous during editing, prevent identity switches, and produce the requested Reel. Tracking identifiers are production-run evidence; they are not linked to an app user's face or facial template.

3. HOW WE USE YOUR DATA
- Account Data: to authenticate you, maintain your profile, display purchases, and contact you when necessary.
- Payment Records: to fulfill purchases and provide authorized viewing or download access.
- Sports Footage: to analyze, edit, quality-check, deliver, and troubleshoot Reels.
- Usage Analytics: to understand product performance and improve the experience.
- Push Tokens: to send service updates you have allowed.

4. DATA SHARING
We do not sell your data. We share data only with service providers required to operate SportReel, such as:
- Supabase — authentication, database, and application state
- Cloudflare — video object storage or delivery
- Stripe or another configured payment provider — payment processing
- Expo — optional push notification delivery
- Hosting and monitoring providers used by the web API and production pipeline

Each provider processes data only for the service it supplies and under its applicable contractual and privacy obligations.

5. DATA RETENTION
- Account data: retained until the account is deleted or retention is otherwise legally required.
- Purchase and transaction records: retained as needed to fulfill purchases, prevent fraud, and meet accounting or legal obligations.
- Source footage and generated Reel files: retained according to the operator and delivery lifecycle, then deleted or archived under the applicable product policy.
- Pipeline diagnostics and tracking evidence: retained only as needed for quality assurance, troubleshooting, and product improvement, subject to access controls.
- Analytics events: retained according to the active analytics retention policy.

6. YOUR RIGHTS
Subject to applicable law, you may request:
- access to personal data held about you;
- correction of inaccurate data;
- deletion of your account and associated personal data where no legal retention duty applies;
- a portable copy of applicable data;
- information about processing and service providers;
- objection or restriction where the law provides that right.

SportReel does not require biometric consent because the app does not collect or process facial biometric templates for account identification. To exercise your rights, use Contact Support in the Profile screen.

7. SECURITY
We use technical and organizational safeguards appropriate to the service, including:
- TLS encryption for data in transit;
- access-controlled storage for source footage and Reels;
- row-level security and service-role boundaries for protected database operations;
- operator authorization for privileged actions;
- restricted access to production diagnostics and tracking evidence.

8. CHILDREN
The App is not intended for users under 16. We do not knowingly collect account data from children under 16 without an appropriate lawful basis and required authorization.

9. DEVICE STORAGE
The App may use secure or device-local storage to maintain login state, operator credentials, upload progress, and other necessary application state.

10. CHANGES
We may update this Privacy Policy. If changes materially affect your rights, we will provide notice through an appropriate product or communication channel.

11. CONTACT
Data Controller: SportReel
Contact: Use the Contact Support option in your Profile screen.
`.trim();
