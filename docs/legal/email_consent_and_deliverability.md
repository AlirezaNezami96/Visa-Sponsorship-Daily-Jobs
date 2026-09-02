# VisaLane Email Consent Classification, Deliverability & Compliance Guide

## 1. Regulatory Consent Classification (GDPR & CAN-SPAM)

Email notifications in VisaLane are partitioned into two strict consent categories to guarantee compliance across EU candidates (GDPR / ePrivacy Directive) and US candidates (CAN-SPAM Act):

### Category A: Transactional / Legitimate Interest Notifications
- **Trigger**: Explicitly initiated or configured by the candidate.
- **Email Types**:
  1. **Job Alert Digest** (`cadence: daily | weekly`): Requested search notifications containing fresh verified sponsorship roles.
  2. **Instant Match Alert** (`cadence: instant`): Real-time notification when a new role matching the candidate's exact filter criteria is indexed.
  3. **Company Sponsorship Policy Alert**: Notification that a company the candidate follows or applied to changed sponsorship verification status.
  4. **Password Reset / Account Security**: Authentication and security notices.
- **Compliance Rules**:
  - Excluded from general marketing opt-out; honors granular individual alert deactivation.
  - Must include sender identity and a working unsubscribe link for that specific alert (`List-Unsubscribe` headers).

### Category B: Marketing & Lifecycle Communications
- **Trigger**: User onboarding milestones or platform inactivity.
- **Email Types**:
  1. **Welcome Series (3-part)**: Educational onboarding, relocation guides, and salary threshold updates.
  2. **Re-engagement (14-day inactivity)**: Reminder of fresh market activity on previous searches.
  3. **Win-back (30 / 60 / 90 days dormant)**: Platform re-introduction for inactive talent.
- **Compliance Rules**:
  - **GDPR Opt-In**: Explicit consent obtained at account signup with unchecked checkbox.
  - **CAN-SPAM Opt-Out**: Includes direct physical mailing address and one-click marketing opt-out.
  - **Suppression Rule**: When `marketing_opt_out: true` is set on the recipient's preference record, all Category B sends are unconditionally suppressed by the backend dispatch engine (`dispatch_email_notification`).

---

## 2. Technical Deliverability Configuration (SPF, DKIM, DMARC)

To prevent spoofing and guarantee high deliverability to candidate primary inboxes (avoiding Google/Yahoo spam penalties effective 2024+):

### 1. SPF (Sender Policy Framework)
- **Record Type**: `TXT`
- **Host**: `@` (visalane.com)
- **Value**: `v=spf1 include:_spf.resend.com ~all`

### 2. DKIM (DomainKeys Identified Mail)
- **Record Type**: `CNAME`
- **Host**: `resend._domainkey.visalane.com`
- **Value**: `feedback._domainkey.resend.com`

### 3. DMARC (Domain-based Message Authentication, Reporting, and Conformance)
- **Record Type**: `TXT`
- **Host**: `_dmarc.visalane.com`
- **Value**: `v=DMARC1; p=reject; sp=reject; pct=100; rua=mailto:dmarc@visalane.com; aspf=r; adkim=r`
- **Alignment Policy**: Strict rejection (`p=reject`) on unauthenticated mail attempting to spoof `@visalane.com`.

---

## 3. RFC 2369 & RFC 8058 One-Click Unsubscribe Headers

All outgoing alerts dispatched by `engine/api/alert_service.py` automatically inject headers required by Gmail and Yahoo Mail:

```http
List-Unsubscribe: <https://visalane.com/api/v1/alerts/unsubscribe?token={TOKEN}>
List-Unsubscribe-Post: List-Unsubscribe=One-Click
Precedence: bulk
Feedback-ID: alert_digest:visalane_alerts:visalane
```

---

## 4. Deliverability Audit Checklist

- [x] Unsubscribe token is stateless, cryptographically signed via HMAC-SHA256, and requires zero user authentication or password entry.
- [x] Zero-match suppression enabled: alerts with 0 new matching opportunities send nothing, preventing recipient alert fatigue.
- [x] Sending domain authenticated with SPF, DKIM, and DMARC `p=reject`.
- [x] Deliverability test benchmark target: $\ge 9.5 / 10$ on mail-tester.com / Google Postmaster Tools.
