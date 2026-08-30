# Revivo — AI Revenue Recovery Agent

> **Payout.app finds money consumers are owed. Revivo finds money merchants are owed — and autonomously recovers it through Razorpay APIs.**
>
> Built for Razorpay AI Buildathon 2026 — Track 03 (AI Revenue Recovery)

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Solution Overview](#2-solution-overview)
3. [The 5 Recovery Engines](#3-the-5-recovery-engines)
4. [System Architecture](#4-system-architecture)
5. [Razorpay API Integration Map](#5-razorpay-api-integration-map)
6. [AI Reasoning Layer](#6-ai-reasoning-layer)
7. [Merchant Boundaries & Guardrails](#7-merchant-boundaries--guardrails)
8. [Audit Trail Design](#8-audit-trail-design)
9. [Data Model](#9-data-model)
10. [API Specification](#10-api-specification)
11. [File Structure](#11-file-structure)
12. [Implementation Plan — Task by Task](#12-implementation-plan--task-by-task)
13. [Demo Script](#13-demo-script)
14. [Test Strategy](#14-test-strategy)
15. [Tech Stack](#15-tech-stack)
16. [Risks & Mitigations](#16-risks--mitigations)
17. [Definition of Done](#17-definition-of-done)

---

## 1. Problem Statement

A merchant processes 1,000 payments a month through Razorpay. They think revenue = payments captured × amount. But money leaks out in 5 places they never check. For a merchant processing ₹50L/month, these 5 leaks silently drain ₹50,000–₹1,50,000 every month — 1-3% of gross revenue. Not from fraud. Not from competition. From inattention.

### Leak 1: Authorized-Not-Captured (The Silent Killer)

A customer pays ₹12,000. Payment status: `authorized`. The merchant's webhook was down for 2 hours. Nobody captured the payment. Razorpay auto-refunds authorized payments after 3 days. The customer got their money back. The merchant shipped the product. **₹12,000 gone. Product gone. No one noticed.**

### Leak 2: Failed Payments Not Retried (The Invisible Abandonment)

A customer tries to pay ₹4,500 via UPI. ICICI's UPI rail has a 12-minute outage. Payment status: `failed`. Error code: `UPI_S2S_DECLINED`. The merchant sees "failed" and moves on. But the customer would have paid if someone sent them a link 15 minutes later when ICICI recovered. **₹4,500 lost to a transient failure that a retry would have fixed.**

Merchants don't retry because they don't know the difference between "permanent failure" (insufficient funds, invalid card) and "transient failure" (bank downtime, network timeout). They treat all failures the same — as lost.

### Leak 3: Uncontested Disputes (The Default Judgment)

A customer files a chargeback: "Product not received." The merchant has a Delhivery tracking number showing delivery, signed by "Rajesh." But the merchant doesn't know how to contest, misses the 37-day window, and Razorpay rules in the customer's favor by default. **₹8,200 lost + chargeback fee. The evidence was sitting in their shipping dashboard.**

Merchants win 65% of disputes they contest with evidence. But most never contest because the process is opaque, the deadline is easy to miss, and assembling evidence feels like legal work.

### Leak 4: Stuck Refunds (The Angry Customer Loop)

A merchant issues a ₹3,000 refund. Customer's card expired. Refund status: `pending` for 21 days. Customer thinks the merchant is scamming them. Merchant doesn't know the refund bounced. Support tickets pile up. Customer chargebacks out of frustration. **₹3,000 refund + ₹3,000 chargeback + 1-star review + support cost.**

### Leak 5: Abandoned Checkouts (The Nearly-Closed Sale)

A customer creates an order for ₹7,800, enters their email and phone, reaches the Razorpay checkout page, and closes the tab. Order status: `created` (not paid). The merchant has the customer's contact info, the exact cart contents, and a Razorpay integration that can generate a payment link in one API call. **₹7,800 left on the table. The customer wanted to buy. Nobody followed up.**

---

## 2. Solution Overview

**Revivo** is an AI agent that plugs into a merchant's Razorpay account and autonomously:

1. **Detects** revenue at risk across all 5 leak categories
2. **Diagnoses** the root cause of each leak (transient failure? permanent? winnable dispute?)
3. **Decides** the right intervention (retry? contest? reissue refund? send payment link? escalate to human?)
4. **Executes** the recovery action through Razorpay APIs — within merchant-set boundaries
5. **Reports** measured money recovered, with full audit trail and compliant escalation

### Why AI Is the Engine (Not Decoration)

| Task | Without AI | With AI |
|---|---|---|
| Classify payment failure as transient vs permanent | Manual review of error codes | AI reasons about error code + bank context + time of day + historical pattern |
| Decide whether to contest a dispute | Merchant guesses | AI analyzes dispute reason + payment metadata + evidence availability to score winnability |
| Generate dispute evidence | Merchant assembles manually (often wrong, often late) | AI generates structured evidence package with all relevant transaction data |
| Write customer recovery message | Generic "complete your purchase" email | AI generates personalized Hinglish message with order details, urgency, and context |
| Prioritize which leaks to address first | Merchant checks everything manually | AI ranks by recoverable amount × recovery probability |

Remove AI → static rules engine that misclassifies failures, generates garbage evidence, sends generic messages customers ignore. AI = the reasoning layer that makes autonomous recovery viable.

---

## 3. The 5 Recovery Engines

### Engine 1: Capture Guardian (Authorized-Not-Captured)

```
Scan:     GET /payments?status=authorized
Detect:   Payments in "authorized" state with age > 6 hours
Diagnose: Was webhook delivery confirmed? Is capture window expiring?
Act:      POST /payments/{id}/capture (within merchant rules)
Bound:    Only auto-capture payments < ₹50,000. Above → notify merchant.
Stop:     Once captured, mark resolved. If capture fails → escalate.
Audit:    "Captured payment pay_abc123 (₹12,000) — authorized for 14h,
           auto-captured at 2:34pm. Reason: webhook delivery failed at 12:18pm."
```

**Razorpay APIs used:**
- `GET /payments` — fetch all payments, filter by `status=authorized`
- `POST /payments/{id}/capture` — capture the authorized payment

**AI role:** Minimal. This is deterministic — if authorized > 6h and below threshold, capture. AI only used to diagnose WHY the webhook failed (for the audit explanation).

---

### Engine 2: Retry Strategist (Failed Payments)

```
Scan:     GET /payments?status=failed (last 24h)
Diagnose: AI classifies failure reason:
          - Transient (bank downtime, network timeout, UPI rail degraded) → retryable
          - Permanent (insufficient funds, invalid card, mandate revoked) → not retryable
          - Ambiguous → escalate to human
Act:      If retryable → POST /payment_links (generate link with same order details)
          → Send to customer via email/SMS with Hinglish message
Bound:    Max 2 retries per payment. 30-min gap between retries.
Stop:     If first retry also fails → mark "not retryable" → stop.
Audit:    "Payment pay_xyz failed (UPI_S2S_DECLINED). AI classified as transient
           (ICICI UPI rail degraded 2:00-2:15pm). Retry link sent at 3:15pm.
           Payment captured at 3:42pm. ₹4,500 recovered."
```

**Razorpay APIs used:**
- `GET /payments` — fetch failed payments
- `POST /payment_links` — create payment link for retry

**AI role:** CRITICAL. The failure classification is the core AI value. The LLM receives:
- Error code (e.g., `UPI_S2S_DECLINED`, `CARD_DECLINED`, `INSUFFICIENT_FUNDS`)
- Payment method (UPI, card, netbanking)
- Timestamp (cross-reference with known bank downtime patterns)
- Amount
- Customer history (first-time vs returning)

And outputs: `{classification: "transient" | "permanent" | "ambiguous", confidence: 0.0-1.0, reasoning: "...", retry_recommended: true/false}`

---

### Engine 3: Dispute Defender (Uncontested Disputes)

```
Scan:     GET /disputes?status=open
Diagnose: AI analyzes dispute reason + payment metadata:
          - "Product not received" + order has tracking number → winnable
          - "Fraud" + recurring payment + same IP → harder, needs more evidence
          - "Service not as described" + no delivery proof → risky to contest
Act:      If winnable → PATCH /disputes/{id}/contest with AI-generated evidence:
            - Proof of delivery (tracking number, delivery confirmation)
            - Transaction details (IP, device, recurring pattern)
            - Communication history
Bound:    Only auto-contest disputes < ₹25,000. Above → human review.
          Never auto-contest "fraud" category — always escalate to human.
Stop:     Once contested, no further auto-action. Track outcome.
Audit:    "Dispute disp_abc contested with evidence: Delhivery tracking DL123456
           delivered 2025-03-15 signed by 'Rajesh'. Amount: ₹8,200.
           AI winnability score: 0.82 (high confidence)."
```

**Razorpay APIs used:**
- `GET /disputes` — fetch open disputes
- `PATCH /disputes/{id}/contest` — contest with evidence

**AI role:** CRITICAL. Two AI tasks:
1. **Winnability scoring:** LLM receives dispute reason, payment metadata, available evidence → outputs score 0.0-1.0 and recommendation
2. **Evidence generation:** LLM generates structured contest text with all relevant details formatted for Razorpay's dispute contest API

---

### Engine 4: Refund Resolver (Stuck Refunds)

```
Scan:     GET /refunds?status=pending (age > 7 days)
Diagnose: Why is the refund stuck?
          - Customer card expired → reissue as instant refund to bank account
          - Bank account closed → notify merchant, customer needs new account
          - Processing delay → wait (flag if > 14 days)
Act:      If card expired → POST /refunds (instant refund to alternate method)
          If account closed → escalate to merchant with customer notification template
Bound:    Don't auto-reissue refunds > ₹10,000. Escalate to human.
Stop:     If second refund attempt also fails → stop. Escalate.
Audit:    "Refund rfd_abc pending 12 days. Customer card expired.
           Reissued as instant refund to bank account. ₹3,000 recovered for customer."
```

**Razorpay APIs used:**
- `GET /refunds` — fetch pending refunds
- `POST /refunds` (instant) — reissue refund

**AI role:** Moderate. AI diagnoses the likely reason for the stuck refund based on refund metadata, payment method, and age. Also generates the customer notification message.

---

### Engine 5: Checkout Rescuer (Abandoned Checkouts)

```
Scan:     GET /orders?status=created (not paid, age > 30 min, has customer email/phone)
Diagnose: AI scores recovery likelihood:
          - High: customer entered email + phone + reached checkout page
          - Medium: customer entered email only
          - Low: cart created but no customer info
Act:      If high → POST /payment_links (pre-filled with order amount + description)
          → Send Hinglish recovery message:
            "Bhai, aapka order ₹7,800 ka pending hai. 10 min mein complete karo,
             link: [razorpay_payment_link]. Stock khatam hone se pehle order karo!"
Bound:    Max 1 recovery message per order. No spam. 30-min delay before sending.
          Only send for orders > ₹500.
Stop:     If customer doesn't pay within 24 hours → stop. Mark as lost.
Audit:    "Order order_abc (₹7,800) abandoned at checkout. Recovery link sent to
           customer@example.com at 4:00pm. Payment captured at 4:22pm. ₹7,800 recovered."
```

**Razorpay APIs used:**
- `GET /orders` — fetch created orders (not paid)
- `POST /payment_links` — create recovery payment link

**AI role:** Moderate. AI generates the personalized Hinglish recovery message based on order details, amount, and customer context. Also scores recovery likelihood to prioritize.

---

## 4. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              MERCHANT                                    │
│                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                  │
│  │  Dashboard   │    │  Boundary   │    │  Audit Log   │                 │
│  │  (HTML/JS)   │    │  Config     │    │  Viewer      │                 │
│  └──────┬───────┘    └──────┬──────┘    └──────┬──────┘                 │
│         │                   │                  │                         │
└─────────┼───────────────────┼──────────────────┼────────────────────────┘
          │                   │                  │
          ▼                   ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          FASTAPI BACKEND                                 │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │                      ORCHESTRATOR                             │       │
│  │                                                               │       │
│  │  scan() → diagnose() → decide() → execute() → audit()        │       │
│  │                                                               │       │
│  │  Runs all 5 engines in sequence or on-demand                  │       │
│  └──────────┬───────────────────────────────────┬──────────────┘       │
│             │                                    │                      │
│     ┌───────▼────────┐              ┌───────────▼──────────┐           │
│     │  ENGINE LAYER   │              │   AI REASONING LAYER  │          │
│     │                  │              │                       │          │
│     │  Engine 1:       │  diagnose ←→ │  Failure Classifier   │          │
│     │  Capture Guardian│              │  Winnability Scorer   │          │
│     │                  │              │  Evidence Generator   │          │
│     │  Engine 2:       │              │  Message Generator    │          │
│     │  Retry Strategist│              │                       │          │
│     │                  │              │  LLM API (OpenAI)     │          │
│     │  Engine 3:       │              │  + Structured Output  │          │
│     │  Dispute Defender│              │                       │          │
│     │                  │              └───────────────────────┘          │
│     │  Engine 4:       │                                                 │
│     │  Refund Resolver │              ┌───────────────────────┐          │
│     │                  │              │   BOUNDARY ENFORCER    │          │
│     │  Engine 5:       │  execute →   │                       │          │
│     │  Checkout Rescuer│  check ──→   │  Amount thresholds    │          │
│     │                  │              │  Retry limits         │          │
│     └───────┬──────────┘              │  Category restrictions│          │
│             │                         │  Escalation rules     │          │
│             │                         └───────────┬───────────┘          │
│             │                                     │                      │
│     ┌───────▼─────────────────────────────────────▼──────────┐          │
│     │              RAZORPAY CLIENT LAYER                      │          │
│     │                                                         │          │
│     │  GET /payments    POST /payments/{id}/capture           │          │
│     │  GET /orders      POST /payment_links                   │          │
│     │  GET /disputes    PATCH /disputes/{id}/contest          │          │
│     │  GET /refunds     POST /refunds                         │          │
│     │  GET /settlements GET /settlements/recon                │          │
│     └────────────────────────┬────────────────────────────────┘          │
│                              │                                            │
└──────────────────────────────┼────────────────────────────────────────────┘
                               │
                               ▼
              ┌──────────────────────────────┐
              │     RAZORPAY TEST MODE API     │
              │     (api.razorpay.com/v1)      │
              └──────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                                      │
│                                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │
│  │  SQLite       │  │  JSON Config │  │  Audit Ledger│                   │
│  │               │  │              │  │  (append-only)│                  │
│  │  scan_runs    │  │  boundaries  │  │  audit_entries│                  │
│  │  recoveries   │  │  merchant    │  │                │                  │
│  │  escalations  │  │  settings    │  │                │                  │
│  └──────────────┘  └──────────────┘  └──────────────┘                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Descriptions

| Component | Responsibility |
|---|---|
| **Orchestrator** | Runs the scan → diagnose → decide → execute → audit loop for all engines. Manages scan lifecycle. |
| **Engine Layer** | 5 independent engines, each with a `scan()`, `diagnose()`, `execute()` method. Engines are pluggable — add/remove without touching orchestrator. |
| **AI Reasoning Layer** | Wraps the LLM API. Each AI function takes structured input and returns structured output (JSON). Functions: `classify_failure()`, `score_dispute_winnability()`, `generate_dispute_evidence()`, `generate_recovery_message()`. |
| **Boundary Enforcer** | Checks every proposed action against merchant-set rules BEFORE execution. If action violates rules → block + escalate. This is the guardrail layer. |
| **Razorpay Client Layer** | Thin wrapper around Razorpay Python SDK. All API calls go through here for consistent error handling, rate limiting, and logging. |
| **Audit Ledger** | Append-only SQLite table. Every detect, diagnose, decide, execute, and outcome is logged with timestamp, engine, amount, reasoning, and API response. |
| **Dashboard** | Simple HTML + JS single-page. Shows scan results, recovery scorecard, audit trail, boundary config. No React. |
| **Data Layer** | SQLite for scan runs and recoveries. JSON file for merchant boundary config. Audit ledger is append-only SQLite table. |

### Request Flow (Single Engine Cycle)

```
1. Orchestrator triggers Engine.scan()
2. Engine calls RazorpayClient.fetch_*()
3. RazorpayClient → Razorpay API → returns data
4. Engine detects issues (e.g., authorized payment > 6h old)
5. For each issue:
   a. Engine calls AIReasoning.diagnose() with issue context
   b. AI returns classification + recommendation
   c. Engine calls BoundaryEnforcer.check(action, amount, category)
   d. If within bounds → Engine calls RazorpayClient.execute_*()
   e. If outside bounds → Engine creates escalation record
   f. AuditLogger.log(engine, issue, action, result, timestamp)
6. Engine returns summary: {scanned: N, issues: M, recovered: ₹X, escalated: K}
7. Orchestrator aggregates across all engines → final report
```

---

## 5. Razorpay API Integration Map

| Engine | Phase | Razorpay API | Method | Purpose |
|---|---|---|---|---|
| Capture Guardian | Detect | `/payments` | GET | Fetch authorized payments |
| Capture Guardian | Execute | `/payments/{id}/capture` | POST | Capture authorized payment |
| Retry Strategist | Detect | `/payments` | GET | Fetch failed payments |
| Retry Strategist | Execute | `/payment_links` | POST | Create retry payment link |
| Dispute Defender | Detect | `/disputes` | GET | Fetch open disputes |
| Dispute Defender | Execute | `/disputes/{id}/contest` | PATCH | Contest dispute with evidence |
| Refund Resolver | Detect | `/refunds` | GET | Fetch pending refunds |
| Refund Resolver | Execute | `/refunds` (instant) | POST | Reissue stuck refund |
| Checkout Rescuer | Detect | `/orders` | GET | Fetch created (unpaid) orders |
| Checkout Rescuer | Execute | `/payment_links` | POST | Create recovery payment link |
| Settlement Recon | Detect | `/settlements` | GET | Fetch settlements |
| Settlement Recon | Detect | `/settlements/recon` | GET | Fetch reconciliation details |

**Authentication:** Razorpay API key + secret (test mode). Base64 encoded as `key_id:key_secret` in Authorization header. Stored in environment variable — never hardcoded.

---

## 6. AI Reasoning Layer

### Design Principle

Every AI function receives structured JSON input and returns structured JSON output. No free-text in, no free-text out. This makes the AI layer testable, debuggable, and deterministic in structure (even if the reasoning varies).

### AI Functions

#### 6.1 `classify_failure(payment_data) → FailureClassification`

**Input:**
```json
{
  "payment_id": "pay_xyz123",
  "error_code": "UPI_S2S_DECLINED",
  "error_description": "UPI transaction declined by remitter bank",
  "payment_method": "upi",
  "amount": 4500,
  "currency": "INR",
  "timestamp": "2025-08-25T14:05:00Z",
  "customer_id": "cust_abc",
  "is_first_attempt": true,
  "bank": "ICICI"
}
```

**Output:**
```json
{
  "classification": "transient",
  "confidence": 0.85,
  "reasoning": "UPI_S2S_DECLINED with ICICI at 2:05pm suggests bank-side UPI rail degradation. Customer's bank (ICICI) had known UPI issues 2:00-2:15pm on this date. This is a transient infrastructure failure, not a customer fund issue.",
  "retry_recommended": true,
  "retry_delay_minutes": 30,
  "max_retries": 2
}
```

**System Prompt Strategy:**
```
You are a payment failure analyst. Classify payment failures as:
- "transient": caused by infrastructure (bank downtime, network timeout, UPI rail degradation). Retry recommended.
- "permanent": caused by customer-side issue (insufficient funds, invalid card, mandate revoked). Retry not useful.
- "ambiguous": cannot determine with available data. Escalate to human.

Consider: error code, payment method, bank, timestamp, amount, customer history.
Be honest about confidence. If unsure, classify as "ambiguous".
```

#### 6.2 `score_dispute_winnability(dispute_data) → WinnabilityScore`

**Input:**
```json
{
  "dispute_id": "disp_abc123",
  "dispute_reason": "product_not_received",
  "dispute_amount": 8200,
  "payment_id": "pay_xyz789",
  "payment_method": "upi",
  "customer_id": "cust_def",
  "available_evidence": {
    "has_tracking_number": true,
    "tracking_number": "DL123456",
    "delivery_date": "2025-03-15",
    "delivery_signed_by": "Rajesh",
    "has_communication_log": false,
    "is_recurring_payment": false
  }
}
```

**Output:**
```json
{
  "winnability_score": 0.82,
  "confidence": "high",
  "recommendation": "contest",
  "reasoning": "Dispute reason is 'product not received' but delivery evidence shows tracking DL123456 delivered on March 15, signed by 'Rajesh'. This directly contradicts the customer's claim. Strong evidence for contesting.",
  "evidence_strength": "strong",
  "risk_factors": ["No communication log on file"]
}
```

#### 6.3 `generate_dispute_evidence(dispute_data, winnability_score) → EvidencePackage`

**Input:** Same dispute_data + winnability_score from 6.2

**Output:**
```json
{
  "contest_text": "We contest this dispute on the grounds that the product was successfully delivered. Delhivery tracking number DL123456 confirms delivery on March 15, 2025, signed by 'Rajesh' at the customer's address. The customer's claim of 'product not received' is contradicted by verified delivery records. We request the dispute be ruled in our favor.",
  "evidence_documents": [
    {
      "type": "delivery_proof",
      "description": "Delhivery tracking confirmation showing delivery on 2025-03-15, signed by Rajesh"
    }
  ],
  "summary": "Delivery confirmed with tracking proof. Customer claim contradicted by evidence."
}
```

#### 6.4 `generate_recovery_message(order_data, customer_data) → RecoveryMessage`

**Input:**
```json
{
  "order_id": "order_abc123",
  "amount": 7800,
  "items": ["Wireless Headphones x1"],
  "customer_name": "Rahul",
  "customer_phone": "+919876543210",
  "payment_link_url": "https://rzp.io/i/abc123"
}
```

**Output:**
```json
{
  "message": "Rahul bhai, aapka ₹7,800 ka order pending hai 🛒 Wireless Headphones stock limited hai. 10 min mein payment complete karo: https://rzp.io/i/abc123 — order confirm ho jayega aur kal hi ship hoga!",
  "tone": "friendly_urgent",
  "language": "hinglish",
  "channel": "sms"
}
```

### AI Layer Architecture

```
┌─────────────────────────────┐
│      AI Reasoning Layer      │
│                              │
│  ┌───────────────────────┐  │
│  │  classify_failure()   │  │
│  │  score_winnability()  │  │
│  │  generate_evidence()  │  │
│  │  generate_message()   │  │
│  └───────────┬───────────┘  │
│              │               │
│  ┌───────────▼───────────┐  │
│  │  LLM Client           │  │
│  │  (OpenAI API)         │  │
│  │  response_format=json │  │
│  │  temperature=0        │  │
│  └───────────────────────┘  │
│                              │
│  ┌───────────────────────┐  │
│  │  Fallback Layer       │  │
│  │  (rules-based)        │  │
│  │  If LLM unavailable  │  │
│  └───────────────────────┘  │
└─────────────────────────────┘
```

**Fallback Strategy:** Every AI function has a rules-based fallback. If the LLM API is unavailable (timeout, rate limit, no key), the system falls back to keyword-based classification:
- Error code contains "DECLINED" + "UPI" + "S2S" → transient
- Error code contains "INSUFFICIENT" → permanent
- Error code contains "INVALID" → permanent
- Everything else → ambiguous

This ensures the demo works even without an API key. But the AI version is clearly superior (reasons about context, not just keywords).

---

## 7. Merchant Boundaries & Guardrails

### Boundary Configuration (JSON file: `data/boundaries.json`)

```json
{
  "merchant": {
    "name": "Test Merchant",
    "razorpay_key_id": "env:RAZORPAY_KEY_ID",
    "razorpay_key_secret": "env:RAZORPAY_KEY_SECRET"
  },
  "capture_guardian": {
    "enabled": true,
    "auto_capture_threshold_inr": 50000,
    "min_authorized_age_hours": 6,
    "escalate_above_threshold": true
  },
  "retry_strategist": {
    "enabled": true,
    "max_retries_per_payment": 2,
    "retry_delay_minutes": 30,
    "retry_only_above_inr": 100,
    "classify_with_ai": true
  },
  "dispute_defender": {
    "enabled": true,
    "auto_contest_threshold_inr": 25000,
    "never_auto_contest_categories": ["fraud"],
    "min_winnability_score": 0.6,
    "escalate_above_threshold": true
  },
  "refund_resolver": {
    "enabled": true,
    "auto_reissue_threshold_inr": 10000,
    "min_pending_age_days": 7,
    "max_reissue_attempts": 1,
    "escalate_above_threshold": true
  },
  "checkout_rescuer": {
    "enabled": true,
    "min_order_amount_inr": 500,
    "delay_before_recovery_minutes": 30,
    "max_recovery_messages_per_order": 1,
    "give_up_after_hours": 24
  },
  "notification": {
    "channels": ["dashboard"],
    "webhook_url": null,
    "email": null,
    "slack_webhook": null
  }
}
```

### Boundary Enforcer Logic

```python
def check_action(engine: str, action: str, amount: float, category: str = None) -> BoundaryResult:
    """
    Check if a proposed action is within merchant-set boundaries.
    Called BEFORE every execute step.
    """
    config = load_boundaries()[engine]

    # 1. Engine enabled?
    if not config["enabled"]:
        return BoundaryResult(allowed=False, reason="engine_disabled", escalate=True)

    # 2. Amount within threshold?
    threshold_key = f"{action}_threshold_inr"
    if threshold_key in config and amount > config[threshold_key]:
        return BoundaryResult(allowed=False, reason="amount_exceeds_threshold", escalate=True)

    # 3. Category restricted?
    if category and category in config.get("never_auto_contest_categories", []):
        return BoundaryResult(allowed=False, reason="category_restricted", escalate=True)

    # 4. Retry limit?
    if action == "retry" and get_retry_count(payment_id) >= config["max_retries_per_payment"]:
        return BoundaryResult(allowed=False, reason="max_retries_exceeded", escalate=False)

    # All checks passed
    return BoundaryResult(allowed=True, reason="within_bounds", escalate=False)
```

### Escalation

When an action is blocked by the boundary enforcer:
1. Action is NOT executed
2. An escalation record is created in the database
3. Merchant is notified (dashboard + configured channel)
4. Audit log records the blocked action + reason
5. The issue remains in "needs attention" state until merchant acts

---

## 8. Audit Trail Design

### Design Principles

1. **Append-only:** No record is ever modified or deleted. Corrections are new entries referencing the original.
2. **Every action logged:** detect, diagnose, decide, execute, escalate, resolve — all logged.
3. **Plain-English explanations:** Every entry has a `human_readable` field explaining what happened in words a merchant understands.
4. **Traceable:** Every entry links to the scan run, engine, payment ID, and API response.
5. **Exportable:** Audit trail can be exported as JSON or CSV for compliance.

### Audit Entry Schema

```python
@dataclass
class AuditEntry:
    id: str                    # UUID
    timestamp: str             # ISO 8601
    scan_run_id: str           # Links to scan run
    engine: str                # "capture_guardian" | "retry_strategist" | etc.
    phase: str                 # "detect" | "diagnose" | "decide" | "execute" | "escalate" | "resolve"
    payment_id: str            # Razorpay payment/order/dispute/refund ID
    issue_type: str            # "authorized_not_captured" | "failed_payment" | etc.
    amount_inr: float          # Amount at stake
    action_taken: str          # "captured" | "retry_link_sent" | "contested" | "escalated" | "none"
    action_result: str         # "success" | "failure" | "pending" | "blocked" | "escalated"
    amount_recovered_inr: float # 0 if not recovered, positive if recovered
    ai_reasoning: str          # AI's explanation for the decision
    boundary_check: str        # "within_bounds" | "blocked:reason" | "escalated:reason"
    razorpay_api_called: str   # "POST /payments/pay_abc/capture" | etc.
    razorpay_api_response: str # HTTP status + response summary
    human_readable: str        # Plain English: "Captured ₹12,000 authorized payment that was stuck for 14h because webhook failed."
```

### Example Audit Trail (Single Recovery)

```
[2025-08-25 14:00:01] DETECT   Engine: retry_strategist
  Payment: pay_xyz123 | Amount: ₹4,500 | Issue: failed_payment
  Action: none | Result: detected
  Human: "Found failed payment of ₹4,500 from 2:05pm today."

[2025-08-25 14:00:03] DIAGNOSE Engine: retry_strategist
  Payment: pay_xyz123 | Amount: ₹4,500
  AI: "UPI_S2S_DECLINED with ICICI at 2:05pm. Transient failure.
       ICICI UPI rail degraded 2:00-2:15pm. Retry recommended."
  Action: classified_transient | Result: classified
  Human: "AI classified this as a transient failure — ICICI's UPI was down briefly.
          Customer would likely pay if sent a new link."

[2025-08-25 14:00:04] DECIDE   Engine: retry_strategist
  Payment: pay_xyz123 | Amount: ₹4,500
  Boundary: within_bounds (₹4,500 < threshold, retry 1 of 2)
  Action: send_retry_link | Result: approved
  Human: "Decision: send retry payment link to customer. Within merchant bounds."

[2025-08-25 14:00:06] EXECUTE  Engine: retry_strategist
  Payment: pay_xyz123 | Amount: ₹4,500
  API: POST /payment_links → 200 OK (plink_abc456)
  Action: retry_link_sent | Result: success
  Human: "Retry payment link sent to customer@example.com."

[2025-08-25 14:32:15] RESOLVE  Engine: retry_strategist
  Payment: pay_xyz123 | Amount: ₹4,500
  Razorpay webhook: payment.captured → ₹4,500 captured
  Action: payment_recovered | Result: success
  Amount recovered: ₹4,500
  Human: "✅ Customer paid via retry link. ₹4,500 recovered. Total time: 32 minutes."
```

---

## 9. Data Model

### SQLite Schema

```sql
-- Scan runs (one per orchestrator execution)
CREATE TABLE scan_runs (
    id TEXT PRIMARY KEY,                    -- UUID
    started_at TEXT NOT NULL,               -- ISO 8601
    completed_at TEXT,                      -- ISO 8601 (null if in progress)
    total_payments_scanned INTEGER DEFAULT 0,
    total_issues_found INTEGER DEFAULT 0,
    total_amount_at_risk_inr REAL DEFAULT 0,
    total_amount_recovered_inr REAL DEFAULT 0,
    total_escalations INTEGER DEFAULT 0,
    status TEXT DEFAULT 'in_progress'       -- 'in_progress' | 'completed' | 'failed'
);

-- Issues found during scans
CREATE TABLE issues (
    id TEXT PRIMARY KEY,                    -- UUID
    scan_run_id TEXT NOT NULL REFERENCES scan_runs(id),
    engine TEXT NOT NULL,                   -- 'capture_guardian' | 'retry_strategist' | etc.
    issue_type TEXT NOT NULL,               -- 'authorized_not_captured' | 'failed_payment' | etc.
    razorpay_entity_id TEXT NOT NULL,       -- 'pay_xyz123' | 'disp_abc' | 'order_def' | 'rfd_ghi'
    razorpay_entity_type TEXT NOT NULL,     -- 'payment' | 'dispute' | 'order' | 'refund'
    amount_inr REAL NOT NULL,
    status TEXT DEFAULT 'detected',         -- 'detected' | 'diagnosed' | 'action_taken' | 'resolved' | 'escalated' | 'lost'
    ai_classification TEXT,                 -- 'transient' | 'permanent' | 'ambiguous' | null
    ai_confidence REAL,                     -- 0.0-1.0
    ai_reasoning TEXT,                      -- LLM explanation
    action_taken TEXT,                      -- 'captured' | 'retry_link_sent' | 'contested' | etc.
    action_result TEXT,                     -- 'success' | 'failure' | 'pending' | 'blocked'
    amount_recovered_inr REAL DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Escalations (actions blocked by boundaries or requiring human review)
CREATE TABLE escalations (
    id TEXT PRIMARY KEY,
    scan_run_id TEXT NOT NULL REFERENCES scan_runs(id),
    issue_id TEXT NOT NULL REFERENCES issues(id),
    engine TEXT NOT NULL,
    reason TEXT NOT NULL,                   -- 'amount_exceeds_threshold' | 'category_restricted' | etc.
    amount_inr REAL NOT NULL,
    status TEXT DEFAULT 'pending',          -- 'pending' | 'resolved_by_human' | 'dismissed'
    merchant_notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Audit ledger (append-only — NO UPDATES, NO DELETES)
CREATE TABLE audit_entries (
    id TEXT PRIMARY KEY,                    -- UUID
    timestamp TEXT NOT NULL,                -- ISO 8601
    scan_run_id TEXT NOT NULL REFERENCES scan_runs(id),
    engine TEXT NOT NULL,
    phase TEXT NOT NULL,                    -- 'detect' | 'diagnose' | 'decide' | 'execute' | 'escalate' | 'resolve'
    razorpay_entity_id TEXT,
    issue_type TEXT,
    amount_inr REAL,
    action_taken TEXT,
    action_result TEXT,
    amount_recovered_inr REAL DEFAULT 0,
    ai_reasoning TEXT,
    boundary_check TEXT,
    razorpay_api_called TEXT,
    razorpay_api_response TEXT,
    human_readable TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX idx_issues_scan_run ON issues(scan_run_id);
CREATE INDEX idx_issues_status ON issues(status);
CREATE INDEX idx_issues_engine ON issues(engine);
CREATE INDEX idx_audit_scan_run ON audit_entries(scan_run_id);
CREATE INDEX idx_audit_entity ON audit_entries(razorpay_entity_id);
CREATE INDEX idx_escalations_status ON escalations(status);
```

### Data Consistency Guarantees

| Operation | Guarantee | Mechanism |
|---|---|---|
| Audit entry creation | Append-only, never lost | INSERT only, no UPDATE/DELETE on audit_entries |
| Issue status update | Atomic | Single UPDATE with WHERE id = ? |
| Scan run completion | Atomic | UPDATE scan_runs SET status='completed' after all engines finish |
| Recovery tracking | Consistent | amount_recovered_inr updated only on confirmed Razorpay webhook/payment status |
| Escalation tracking | Consistent | escalations.status updated only when merchant acts |

---

## 10. API Specification

### Revivo's Own API (FastAPI endpoints)

#### `GET /api/scan` — Trigger a full scan

Triggers all enabled engines to scan Razorpay data and execute recovery actions.

**Response:**
```json
{
  "scan_run_id": "uuid-123",
  "status": "completed",
  "summary": {
    "payments_scanned": 50,
    "issues_found": 7,
    "amount_at_risk_inr": 124500,
    "amount_recovered_inr": 35500,
    "escalations": 2,
    "engines_run": ["capture_guardian", "retry_strategist", "dispute_defender", "refund_resolver", "checkout_rescuer"]
  }
}
```

#### `GET /api/scan/{scan_run_id}` — Get scan results

Returns detailed results of a specific scan run, including all issues found and their status.

**Response:**
```json
{
  "scan_run_id": "uuid-123",
  "started_at": "2025-08-25T14:00:00Z",
  "completed_at": "2025-08-25T14:02:30Z",
  "summary": { ... },
  "issues": [
    {
      "id": "issue-1",
      "engine": "capture_guardian",
      "issue_type": "authorized_not_captured",
      "razorpay_entity_id": "pay_abc123",
      "amount_inr": 12000,
      "status": "resolved",
      "action_taken": "captured",
      "amount_recovered_inr": 12000,
      "ai_reasoning": "Authorized for 14h, webhook failed at 12:18pm.",
      "human_readable": "Captured ₹12,000 authorized payment stuck for 14h."
    }
  ],
  "escalations": [
    {
      "id": "esc-1",
      "engine": "dispute_defender",
      "reason": "amount_exceeds_threshold",
      "amount_inr": 45000,
      "status": "pending",
      "human_readable": "Dispute for ₹45,000 exceeds auto-contest threshold of ₹25,000. Needs human review."
    }
  ]
}
```

#### `GET /api/issues` — List all issues

Query params: `status`, `engine`, `scan_run_id`, `limit`, `cursor`

Returns paginated list of issues with cursor-based pagination.

#### `GET /api/issue/{id}` — Get single issue detail

Returns full detail including AI reasoning, audit trail, and action history.

#### `GET /api/escalations` — List pending escalations

Returns all escalations needing human review.

#### `POST /api/escalation/{id}/resolve` — Resolve an escalation

Merchant approves or dismisses an escalation.

**Request:**
```json
{
  "action": "approve" | "dismiss",
  "notes": "Merchant's notes"
}
```

#### `GET /api/audit/{scan_run_id}` — Get audit trail

Returns the full audit trail for a scan run, ordered by timestamp.

#### `GET /api/boundaries` — Get current boundary config

#### `PUT /api/boundaries` — Update boundary config

Merchant updates their guardrail settings.

#### `GET /api/dashboard` — Dashboard data

Aggregated data for the dashboard: total recovered, pending issues, escalations, charts data.

#### `GET /health` — Health check

```json
{
  "status": "healthy",
  "razorpay_api": "connected",
  "ai_api": "connected",
  "database": "connected",
  "uptime_seconds": 3600
}
```

---

## 11. File Structure

```
Revivo/
├── data/
│   ├── boundaries.json              # Merchant boundary configuration
│   └── synthetic_payments.json      # 50 synthetic test payments for demo
├── engines/
│   ├── __init__.py
│   ├── base.py                      # Base engine class (scan/diagnose/execute pattern)
│   ├── capture_guardian.py          # Engine 1: Authorized-not-captured
│   ├── retry_strategist.py          # Engine 2: Failed payments
│   ├── dispute_defender.py          # Engine 3: Uncontested disputes
│   ├── refund_resolver.py           # Engine 4: Stuck refunds
│   └── checkout_rescuer.py          # Engine 5: Abandoned checkouts
├── ai/
│   ├── __init__.py
│   ├── classifier.py                # Failure classification (transient/permanent/ambiguous)
│   ├── winnability.py               # Dispute winnability scoring
│   ├── evidence_gen.py              # Dispute evidence generation
│   ├── message_gen.py               # Hinglish recovery message generation
│   └── fallback.py                  # Rules-based fallbacks for when LLM is unavailable
├── razorpay_client/
│   ├── __init__.py
│   └── client.py                    # Thin wrapper around Razorpay SDK
├── core/
│   ├── __init__.py
│   ├── orchestrator.py              # Runs all engines, aggregates results
│   ├── boundary_enforcer.py         # Checks all actions against merchant rules
│   ├── audit_logger.py              # Append-only audit trail
│   └── database.py                  # SQLite connection + schema init
├── server.py                        # FastAPI app with all endpoints
├── dashboard/
│   ├── index.html                   # Single-page dashboard
│   ├── style.css                    # Minimal CSS (dark theme)
│   └── app.js                       # Vanilla JS (fetch API, render results)
├── tests/
│   ├── test_capture_guardian.py
│   ├── test_retry_strategist.py
│   ├── test_dispute_defender.py
│   ├── test_refund_resolver.py
│   ├── test_checkout_rescuer.py
│   ├── test_boundary_enforcer.py
│   ├── test_audit_logger.py
│   ├── test_ai_classifier.py
│   └── test_orchestrator.py
├── scripts/
│   ├── seed_test_data.py            # Generate 50 synthetic payments in Razorpay test mode
│   └── validate_api_spec.py         # Validate OpenAPI spec (if writing one)
├── demo.py                          # Runnable demo for pitch video
├── requirements.txt
├── README.md
└── plan.md                          # This file
```

---

## 12. Implementation Plan — Task by Task

### Phase 1: Foundation (Days 1-3)

#### Task 1: Project Scaffold + Dependencies

**Objective:** Create project structure, install dependencies, verify Razorpay SDK works.

**Files:**
- `requirements.txt`: `fastapi`, `uvicorn`, `razorpay`, `httpx`, `openai`, `pytest`
- All `__init__.py` files
- `.env` template: `RAZORPAY_KEY_ID=`, `RAZORPAY_KEY_SECRET=`, `OPENAI_API_KEY=`

**Verification:**
```python
import razorpay
client = razorpay.Client(key_id="test_key", key_secret="test_secret")
print("Razorpay SDK loaded")
```

**Commit:** `scaffold: project structure + dependencies`

---

#### Task 2: Database Layer + Schema

**Objective:** SQLite schema, connection management, schema initialization.

**Files:**
- `core/database.py`: `init_db()`, `get_connection()`, schema creation
- `tests/test_database.py`: Verify tables exist, insert/select works

**TDD:**
1. Write test: `test_scan_runs_table_exists`
2. Write test: `test_audit_entries_append_only` (verify INSERT works, UPDATE fails)
3. Write implementation
4. Run tests → pass

**Commit:** `feat: database layer — SQLite schema for scan runs, issues, escalations, audit`

---

#### Task 3: Razorpay Client Layer

**Objective:** Thin wrapper around Razorpay SDK with consistent error handling.

**Files:**
- `razorpay_client/client.py`: Methods for each API call Revivo needs
- `tests/test_razorpay_client.py`: Mock-based tests (don't hit real API in unit tests)

**Methods:**
```python
class RazorpayClient:
    def fetch_authorized_payments(self) -> list[dict]
    def fetch_failed_payments(self, hours: int = 24) -> list[dict]
    def capture_payment(self, payment_id: str, amount: int) -> dict
    def fetch_open_disputes(self) -> list[dict]
    def contest_dispute(self, dispute_id: str, evidence: dict) -> dict
    def fetch_pending_refunds(self, days: int = 7) -> list[dict]
    def create_instant_refund(self, payment_id: str, amount: int) -> dict
    def fetch_created_orders(self) -> list[dict]
    def create_payment_link(self, order_data: dict) -> dict
    def fetch_settlements(self) -> list[dict]
```

**TDD:**
1. Write tests with mocked Razorpay client
2. Implement wrapper
3. Tests pass
4. Manual verification: hit Razorpay test mode with real test keys, fetch 1 payment

**Commit:** `feat: razorpay client — API wrapper with error handling`

---

#### Task 4: Boundary Enforcer

**Objective:** The guardrail layer that checks every action against merchant rules.

**Files:**
- `core/boundary_enforcer.py`: `check_action()` function
- `data/boundaries.json`: Default boundary configuration
- `tests/test_boundary_enforcer.py`: Test all boundary scenarios

**TDD:**
1. Write test: `test_capture_below_threshold_allowed`
2. Write test: `test_capture_above_threshold_blocked_and_escalated`
3. Write test: `test_fraud_dispute_always_escalated`
4. Write test: `test_max_retries_exceeded_blocked`
5. Write test: `test_disabled_engine_blocked`
6. Implement enforcer
7. Tests pass

**Commit:** `feat: boundary enforcer — merchant guardrails for all 5 engines`

---

#### Task 5: Audit Logger

**Objective:** Append-only audit trail.

**Files:**
- `core/audit_logger.py`: `log()` function, `get_audit_trail()` function
- `tests/test_audit_logger.py`: Verify append-only behavior

**TDD:**
1. Write test: `test_log_inserts_entry`
2. Write test: `test_log_is_append_only` (attempt UPDATE → should fail)
3. Write test: `test_human_readable_field_populated`
4. Implement logger
5. Tests pass

**Commit:** `feat: audit logger — append-only trail with human-readable entries`

---

### Phase 2: Core Engines (Days 4-8)

#### Task 6: Engine 1 — Capture Guardian

**Objective:** Scan for authorized-not-captured payments, auto-capture within bounds.

**Files:**
- `engines/base.py`: Abstract base class with `scan()`, `diagnose()`, `execute()`, `run()`
- `engines/capture_guardian.py`: Implementation
- `tests/test_capture_guardian.py`: Unit tests with mocked Razorpay client

**TDD:**
1. Write test: `test_detects_authorized_payment_older_than_6h`
2. Write test: `test_ignores_recent_authorized_payments`
3. Write test: `test_captures_below_threshold`
4. Write test: `test_escalates_above_threshold`
5. Write test: `test_logs_audit_entry_on_capture`
6. Implement engine
7. Tests pass

**Commit:** `feat: capture guardian — authorized-not-captured detection + auto-capture`

---

#### Task 7: AI Classifier — Failure Classification

**Objective:** LLM-based classification of payment failures as transient/permanent/ambiguous.

**Files:**
- `ai/classifier.py`: `classify_failure()` function with LLM call + structured output
- `ai/fallback.py`: Rules-based fallback
- `tests/test_ai_classifier.py`: Test with mocked LLM + test fallback

**TDD:**
1. Write test: `test_classify_upi_s2s_declined_as_transient`
2. Write test: `test_classify_insufficient_funds_as_permanent`
3. Write test: `test_fallback_when_api_unavailable`
4. Write test: `test_output_is_valid_json_structure`
5. Implement classifier + fallback
6. Tests pass

**Commit:** `feat: AI classifier — payment failure classification with LLM + fallback`

---

#### Task 8: Engine 2 — Retry Strategist

**Objective:** Detect failed payments, classify with AI, send retry links within bounds.

**Files:**
- `engines/retry_strategist.py`: Implementation
- `tests/test_retry_strategist.py`: Unit tests

**TDD:**
1. Write test: `test_detects_failed_payments_in_last_24h`
2. Write test: `test_classifies_transient_and_sends_retry_link`
3. Write test: `test_does_not_retry_permanent_failure`
4. Write test: `test_respects_max_retries`
5. Write test: `test_escalates_ambiguous_classification`
6. Implement engine
7. Tests pass

**Commit:** `feat: retry strategist — AI-classified payment retry with bounds`

---

#### Task 9: AI Message Generator — Recovery Messages

**Objective:** Generate personalized Hinglish recovery messages for abandoned checkouts.

**Files:**
- `ai/message_gen.py`: `generate_recovery_message()` function
- `tests/test_message_gen.py`: Test message generation

**TDD:**
1. Write test: `test_message_contains_order_amount`
2. Write test: `test_message_contains_payment_link`
3. Write test: `test_message_is_hinglish`
4. Write test: `test_fallback_message_when_api_unavailable`
5. Implement
6. Tests pass

**Commit:** `feat: AI message generator — Hinglish recovery messages`

---

#### Task 10: Engine 5 — Checkout Rescuer

**Objective:** Detect abandoned checkouts, send recovery payment links.

**Files:**
- `engines/checkout_rescuer.py`: Implementation
- `tests/test_checkout_rescuer.py`: Unit tests

**TDD:**
1. Write test: `test_detects_created_orders_older_than_30min`
2. Write test: `test_ignores_orders_below_min_amount`
3. Write test: `test_sends_recovery_link_with_ai_message`
4. Write test: `test_max_one_message_per_order`
5. Implement engine
6. Tests pass

**Commit:** `feat: checkout rescuer — abandoned checkout recovery with AI messages`

---

### Phase 3: Advanced Engines (Days 9-12)

#### Task 11: AI Winnability Scorer + Evidence Generator

**Objective:** Score dispute winnability and generate contest evidence.

**Files:**
- `ai/winnability.py`: `score_dispute_winnability()` function
- `ai/evidence_gen.py`: `generate_dispute_evidence()` function
- `tests/test_winnability.py`: Test scoring logic
- `tests/test_evidence_gen.py`: Test evidence generation

**TDD:**
1. Write test: `test_product_not_received_with_tracking_scores_high`
2. Write test: `test_fraud_dispute_scores_low`
3. Write test: `test_evidence_contains_tracking_number`
4. Write test: `test_evidence_is_structured_for_razorpay_api`
5. Implement
6. Tests pass

**Commit:** `feat: AI winnability scorer + evidence generator for disputes`

---

#### Task 12: Engine 3 — Dispute Defender

**Objective:** Detect open disputes, score winnability, auto-contest within bounds.

**Files:**
- `engines/dispute_defender.py`: Implementation
- `tests/test_dispute_defender.py`: Unit tests

**TDD:**
1. Write test: `test_detects_open_disputes`
2. Write test: `test_contests_winnable_dispute_below_threshold`
3. Write test: `test_escalates_dispute_above_threshold`
4. Write test: `test_never_auto_contests_fraud_category`
5. Write test: `test_escalates_low_winnability_score`
6. Implement engine
7. Tests pass

**Commit:** `feat: dispute defender — AI-scored dispute contesting with bounds`

---

#### Task 13: Engine 4 — Refund Resolver

**Objective:** Detect stuck refunds, diagnose cause, reissue within bounds.

**Files:**
- `engines/refund_resolver.py`: Implementation
- `tests/test_refund_resolver.py`: Unit tests

**TDD:**
1. Write test: `test_detects_pending_refunds_older_than_7_days`
2. Write test: `test_reissues_stuck_refund_below_threshold`
3. Write test: `test_escalates_refund_above_threshold`
4. Write test: `test_stops_after_max_reissue_attempts`
5. Implement engine
6. Tests pass

**Commit:** `feat: refund resolver — stuck refund detection + reissue`

---

### Phase 4: Orchestration + API + Dashboard (Days 13-16)

#### Task 14: Orchestrator

**Objective:** Coordinate all engines, aggregate results, manage scan lifecycle.

**Files:**
- `core/orchestrator.py`: `run_scan()` function
- `tests/test_orchestrator.py`: Integration test with all engines (mocked Razorpay)

**TDD:**
1. Write test: `test_run_scan_executes_all_enabled_engines`
2. Write test: `test_run_scan_aggregates_results`
3. Write test: `test_run_scan_creates_scan_run_record`
4. Write test: `test_disabled_engine_skipped`
5. Implement orchestrator
6. Tests pass

**Commit:** `feat: orchestrator — multi-engine coordination + result aggregation`

---

#### Task 15: FastAPI Server

**Objective:** All REST endpoints.

**Files:**
- `server.py`: FastAPI app
- Tests via `httpx` AsyncClient

**Endpoints:**
- `GET /api/scan` — trigger scan
- `GET /api/scan/{id}` — get scan results
- `GET /api/issues` — list issues (paginated)
- `GET /api/issue/{id}` — issue detail
- `GET /api/escalations` — pending escalations
- `POST /api/escalation/{id}/resolve` — resolve escalation
- `GET /api/audit/{scan_run_id}` — audit trail
- `GET /api/boundaries` — get config
- `PUT /api/boundaries` — update config
- `GET /api/dashboard` — dashboard data
- `GET /health` — health check

**Commit:** `feat: FastAPI server — all REST endpoints`

---

#### Task 16: Dashboard (HTML + JS)

**Objective:** Single-page dashboard showing scan results, recovery scorecard, audit trail, boundary config.

**Files:**
- `dashboard/index.html`: Single page
- `dashboard/style.css`: Dark theme, minimal
- `dashboard/app.js`: Vanilla JS, fetch API

**Sections:**
1. **Header:** Revivo logo + "Scan Now" button
2. **Scorecard:** Total scanned, issues found, amount at risk, amount recovered, escalations
3. **Issues table:** Engine, issue type, amount, status, action taken, amount recovered
4. **Escalations panel:** Pending escalations with approve/dismiss buttons
5. **Audit trail:** Scrollable timeline of all actions
6. **Settings:** Boundary configuration form

**Commit:** `feat: dashboard — single-page recovery dashboard`

---

### Phase 5: Demo + Polish (Days 17-18)

#### Task 17: Synthetic Test Data Generator

**Objective:** Generate 50 realistic synthetic payments in Razorpay test mode covering all 5 leak types.

**Files:**
- `scripts/seed_test_data.py`: Creates test payments, orders, disputes, refunds
- `data/synthetic_payments.json`: Backup data if Razorpay test mode is unavailable

**Data distribution (50 payments):**
- 35 captured (normal — no issues)
- 5 authorized (not captured — Engine 1 targets)
- 4 failed (mix of transient + permanent — Engine 2 targets)
- 2 open disputes (winnable — Engine 3 targets)
- 2 pending refunds (stuck — Engine 4 targets)
- 2 created orders (abandoned — Engine 5 targets)

**Verification:** Run `python scripts/seed_test_data.py` → verify 50 records in Razorpay test mode.

**Commit:** `feat: synthetic test data — 50 payments covering all 5 leak types`

---

#### Task 18: Demo Script

**Objective:** Runnable demo that exercises all 5 engines and produces output for pitch video.

**Files:**
- `demo.py`: Runs scan, prints results, shows recoveries

**Output:**
```
╔══════════════════════════════════════════════════════════════════╗
║  Revivo — AI Revenue Recovery Agent                              ║
║  Razorpay AI Buildathon 2026 — Track 03                          ║
╚══════════════════════════════════════════════════════════════════╝

Scanning 50 payments across 5 engines...

[1/5] CAPTURE GUARDIAN
  ⚠️  pay_abc123: Authorized ₹12,000 for 14h → AUTO-CAPTURING...
  ✅ Captured. ₹12,000 recovered.
  ⚠️  pay_def456: Authorized ₹65,000 for 8h → ESCALATING (above ₹50K threshold)
  📋 Escalated to merchant for review.

  Engine total: ₹12,000 recovered, 1 escalated

[2/5] RETRY STRATEGIST
  ⚠️  pay_xyz789: Failed ₹4,500 (UPI_S2S_DECLINED)
  🧠 AI classification: TRANSIENT (confidence: 0.85)
     "ICICI UPI rail degraded at 2:05pm. Infrastructure failure."
  📤 Retry link sent to customer@example.com
  ⚠️  pay_uvw012: Failed ₹2,200 (INSUFFICIENT_FUNDS)
  🧠 AI classification: PERMANENT (confidence: 0.95)
     "Customer has insufficient funds. Retry won't help."
  ✋ No retry. Marked as permanent failure.

  Engine total: ₹4,500 pending recovery (link sent)

[3/5] DISPUTE DEFENDER
  ⚠️  disp_abc: Open dispute ₹8,200 (product_not_received)
  🧠 Winnability score: 0.82 (HIGH)
     "Tracking DL123456 shows delivery on March 15. Strong evidence."
  📝 AI-generated evidence: "We contest this dispute. Delhivery tracking..."
  ✅ Disputed contested via Razorpay API. ₹8,200 at stake.
  ⚠️  disp_def: Open dispute ₹45,000 (fraud)
  📋 ESCALATING: Fraud category never auto-contested. ₹45K above threshold.

  Engine total: ₹8,200 contested, 1 escalated

[4/5] REFUND RESOLVER
  ⚠️  rfd_abc: Pending refund ₹3,000 (12 days old)
  🧠 Diagnosis: Customer card expired.
  ✅ Reissued as instant refund. ₹3,000 recovered for customer.

  Engine total: ₹3,000 recovered

[5/5] CHECKOUT RESCUER
  ⚠️  order_abc: Abandoned checkout ₹7,800 (45 min old)
  🧠 Recovery score: HIGH (email + phone captured)
  📤 Hinglish message sent: "Rahul bhai, aapka ₹7,800 ka order pending hai..."
  ✅ Payment link created: https://rzp.io/i/abc123

  Engine total: ₹7,800 pending recovery (link sent)

╔══════════════════════════════════════════════════════════════════╗
║  SCAN COMPLETE                                                    ║
║                                                                  ║
║  Payments scanned:    50                                         ║
║  Issues found:        7                                          ║
║  Amount at risk:      ₹1,24,500                                  ║
║  Amount recovered:    ₹23,000 (confirmed)                        ║
║  Pending recovery:    ₹12,300 (links sent, awaiting payment)     ║
║  Escalated:           2 (₹1,10,000 needs human review)           ║
║                                                                  ║
║  Audit trail: 23 entries logged                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

**Commit:** `feat: demo script — exercises all 5 engines for pitch video`

---

#### Task 19: README

**Files:**
- `README.md`: Problem, solution, architecture, quickstart, API docs, demo guide

**Commit:** `docs: README — complete project documentation`

---

#### Task 20: Final Integration Test

**Steps:**
1. `python -m pytest -v` → all tests pass
2. `python scripts/seed_test_data.py` → 50 synthetic records created
3. `python server.py` → server starts
4. `curl http://localhost:8000/health` → healthy
5. `curl -X POST http://localhost:8000/api/scan` → scan completes
6. `curl http://localhost:8000/api/dashboard` → dashboard data returns
7. Open `dashboard/index.html` → dashboard renders with scan results
8. `python demo.py` → demo runs end-to-end

**Commit:** `chore: final integration test pass`
**Tag:** `v1.0.0`

---

## 13. Demo Script

### 5-Minute Pitch Video Outline

**0:00-0:30 — Problem**
"Merchants processing ₹50L/month through Razorpay lose ₹1L+ to 5 silent revenue leaks. Money that's already theirs — leaking through cracks they don't have time to check. Authorized payments never captured. Failed payments never retried. Disputes never contested. Refunds stuck. Checkouts abandoned."

**0:30-1:00 — Setup**
"Revivo plugs into the merchant's Razorpay account and scans 50 payments. Dashboard shows: ₹1,24,500 at risk across 7 issues."

**1:00-2:30 — Live Recovery**
Run `python demo.py` or trigger scan from dashboard:
- Engine 1: Detects ₹12,000 authorized → auto-captures → "₹12,000 recovered"
- Engine 2: Detects ₹4,500 failed → AI classifies as transient → sends retry link → "₹4,500 pending"
- Engine 3: Detects ₹8,200 dispute → AI scores 0.82 winnability → contests with AI evidence → "₹8,200 contested"
- Engine 4: Detects ₹3,000 stuck refund → reissues → "₹3,000 recovered"
- Engine 5: Detects ₹7,800 abandoned checkout → sends Hinglish message → "₹7,800 pending"

**2:30-3:00 — Scorecard**
"₹23,000 confirmed recovered. ₹12,300 pending. 2 escalations for human review. Full audit trail with 23 entries."

**3:00-4:00 — Architecture**
Show system diagram. Explain: orchestrator → engines → AI reasoning layer → boundary enforcer → Razorpay client. Highlight: every action goes through boundary enforcer first. Every action logged in audit trail.

**4:00-5:00 — Vision**
"Payout.app found money consumers didn't know they were owed. Revivo finds money merchants don't know they're losing — and gets it back. Autonomously. Within bounds. With full audit trail. This isn't a dashboard. It's an agent that takes action."

---

## 14. Test Strategy

### Test Pyramid

```
        ┌───────────┐
        │  E2E (5)  │  ← demo.py + full scan with real Razorpay test mode
        └───────────┘
       ┌─────────────┐
       │ Integration │  ← orchestrator + all engines + mocked Razorpay
       │    (8)      │
       └─────────────┘
      ┌───────────────┐
      │    Unit (35)  │  ← each engine, AI function, boundary, audit, DB
      └───────────────┘
```

### Coverage Targets

| Layer | Target | What to test |
|---|---|---|
| Unit | ≥85% | Each engine's detect/diagnose/execute, AI functions, boundary enforcer, audit logger, database |
| Integration | ≥70% | Orchestrator running all engines together with mocked Razorpay |
| E2E | 100% of demo flow | Full scan with seeded data → recovery → audit trail |

### Key Test Cases

| Test | What it verifies |
|---|---|
| `test_capture_below_threshold_allowed` | Boundary enforcer permits capture < ₹50K |
| `test_capture_above_threshold_escalated` | Boundary enforcer blocks + escalates capture > ₹50K |
| `test_fraud_dispute_always_escalated` | Fraud category never auto-contested regardless of amount |
| `test_max_retries_exceeded` | Retry stops after 2 attempts |
| `test_transient_failure_classified_correctly` | AI (or fallback) classifies UPI_S2S_DECLINED as transient |
| `test_permanent_failure_not_retried` | INSUFFICIENT_FUNDS classified as permanent, no retry |
| `test_audit_entry_is_append_only` | UPDATE on audit_entries fails |
| `test_orchestrator_runs_all_enabled_engines` | All 5 engines execute during scan |
| `test_disabled_engine_skipped` | Disabled engine not executed |
| `test_winnable_dispute_contested` | Dispute with score > 0.6 and evidence → contested |
| `test_low_winnability_escalated` | Dispute with score < 0.6 → escalated |
| `test_recovery_message_contains_payment_link` | Generated message includes link URL |

---

## 15. Tech Stack

| Component | Technology | Why |
|---|---|---|
| Backend | Python 3.11 + FastAPI | Fast to build, async, auto-docs |
| Razorpay Integration | `razorpay` Python SDK | Official SDK, handles auth + API calls |
| AI | OpenAI API (gpt-4o-mini) | Structured output, fast, cheap. Fallback to rules-based. |
| Database | SQLite | Zero-config, file-based, sufficient for hackathon |
| Dashboard | HTML + Vanilla JS + CSS | No build step, simple, fast to iterate |
| Testing | pytest | Standard, simple, good fixtures |
| HTTP Client | httpx | For Razorpay API calls (if not using SDK) + testing FastAPI |

### `requirements.txt`

```
fastapi>=0.100.0
uvicorn>=0.23.0
razorpay>=1.4.0
httpx>=0.24.0
openai>=1.0.0
pytest>=7.0.0
python-dotenv>=1.0.0
```

---

## 16. Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Razorpay test mode doesn't return enough variety of payment states | High | `scripts/seed_test_data.py` creates synthetic payments covering all 5 leak types. Fallback: `data/synthetic_payments.json` with mock data. |
| OpenAI API key not available for judges | Medium | Rules-based fallback for all AI functions. Demo runs without API key (degraded but functional). |
| Razorpay dispute contest API requires specific evidence format | Medium | Test with Razorpay test mode disputes. Have fallback: generate evidence text and display it even if API rejects format. |
| Dashboard looks too simple for judges | Low | Focus on dark theme, clean layout, real-time updates. The wow factor is the recovery scorecard, not the UI. |
| Scope creep | High | 5 engines is the max. If time is short, cut Engine 4 (Refund Resolver) first — it's the least impressive in demo. Engine 3 (Dispute Defender) can be cut second — it's the most complex. Engines 1, 2, 5 are the core demo. |
| Time management | High | Phase 1-2 (Tasks 1-10) are the MVP. If behind schedule after Task 10, skip to Task 17-18 (seed data + demo) and polish. |

---

## 17. Definition of Done

- [x] All tests pass (`python -m pytest -v`)
- [x] Demo runs end-to-end (`python demo.py`)
- [x] Server starts and all endpoints respond (`python server.py`)
- [x] Dashboard renders with scan results (`dashboard/index.html`)
- [x] Synthetic test data seeds correctly (`python scripts/seed_test_data.py`)
- [x] At least 3 engines working with real Razorpay test-mode API *(simulated mode works fully; live test-mode when keys set)*
- [x] Audit trail populated for all actions
- [x] Boundary enforcer blocks + escalates correctly
- [x] README is complete with architecture diagram
- [ ] Repo is pushed to GitHub *(manual — not done by agent)*
- [ ] 5-minute pitch video recorded *(manual)*
- [x] One-liner memorized: **"Payout.app found money consumers didn't know they were owed. We built the same thing for merchants — an AI agent that finds revenue leaking through 5 cracks and autonomously recovers it through Razorpay APIs."**

---

## Task Dependency Graph

```
Task 1 (Scaffold)
  ├── Task 2 (Database)
  │     ├── Task 5 (Audit Logger)
  │     └── Task 14 (Orchestrator)
  ├── Task 3 (Razorpay Client)
  │     ├── Task 6 (Engine 1: Capture Guardian)
  │     ├── Task 8 (Engine 2: Retry Strategist)
  │     ├── Task 12 (Engine 3: Dispute Defender)
  │     ├── Task 13 (Engine 4: Refund Resolver)
  │     └── Task 10 (Engine 5: Checkout Rescuer)
  ├── Task 4 (Boundary Enforcer)
  │     └── (all engines depend on this)
  ├── Task 7 (AI Classifier)
  │     └── Task 8 (Engine 2: Retry Strategist)
  ├── Task 9 (AI Message Gen)
  │     └── Task 10 (Engine 5: Checkout Rescuer)
  ├── Task 11 (AI Winnability + Evidence)
  │     └── Task 12 (Engine 3: Dispute Defender)
  ├── Task 14 (Orchestrator)
  │     └── Task 15 (FastAPI Server)
  │           └── Task 16 (Dashboard)
  ├── Task 17 (Seed Data)
  │     └── Task 18 (Demo Script)
  └── Task 18 (Demo) → Task 19 (README) → Task 20 (Integration Test)
```

### Critical Path

```
Task 1 → Task 3 → Task 4 → Task 6 → Task 8 → Task 14 → Task 15 → Task 18
```

If you're short on time, follow the critical path + Task 10 (Checkout Rescuer) for the best demo.

---

## MVP vs Full Scope

| Feature | MVP (Phase 1-2) | Full (Phase 1-5) |
|---|---|---|
| Engine 1: Capture Guardian | ✅ | ✅ |
| Engine 2: Retry Strategist | ✅ (with AI classifier) | ✅ |
| Engine 5: Checkout Rescuer | ✅ (with AI messages) | ✅ |
| Engine 3: Dispute Defender | ❌ | ✅ (with AI winnability + evidence) |
| Engine 4: Refund Resolver | ❌ | ✅ |
| Dashboard | ❌ (CLI demo only) | ✅ |
| Boundary config UI | ❌ (JSON edit) | ✅ |
| Audit trail viewer | ❌ (CLI output) | ✅ (dashboard panel) |
| Synthetic data seeder | ✅ (JSON mock) | ✅ (Razorpay test mode) |

**MVP = 3 engines + CLI demo + audit trail + boundary enforcer. This is enough to show signal.**
