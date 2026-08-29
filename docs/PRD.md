# PRD — Reclaim: AI Revenue Recovery Agent

> **Razorpay AI Buildathon 2026 — Track 3: AI Revenue Recovery**
> Spec-driven development. This document is the product contract. Code implements this contract. Tests verify it.

---

## 1. Problem Statement

Merchants on Razorpay lose revenue across 5 silent leak channels — money that's authorized but never captured, payments that fail without retry, disputes that go uncontested because nobody saw them in time, refunds that get stuck in pending limbo, and checkouts that are abandoned at the final step. These leaks are individually small, collectively significant: a mid-size merchant can lose ₹2–5 lakh/month without realizing it.

The problem isn't that the data is missing — Razorpay's APIs expose every payment, dispute, refund, and order. The problem is that no merchant has the time to manually scan thousands of transactions daily, diagnose each one, determine the right intervention, and execute it. By the time someone notices an authorized payment past its capture window, the money is gone.

## 2. Target User

**Razorpay merchant** (small-to-mid-size e-commerce, SaaS, or D2C business) processing 100–10,000 transactions/month. Has a Razorpay account with Test Mode API keys. Does not have a dedicated finance ops team to manually audit every transaction.

## 3. Solution Overview

Reclaim is an AI agent that runs a **detect → diagnose → intervene → report** loop against a merchant's Razorpay account via Test Mode APIs:

1. **Detect**: Scan payments, orders, disputes, and refunds via Razorpay APIs to find revenue at risk across 5 leak types
2. **Diagnose**: Classify each leak, determine root cause, assess recoverability
3. **Intervene**: Execute the appropriate recovery action (capture, retry, contest, expedite, re-engage) via Razorpay APIs with bounded actions and stopping rules
4. **Report**: Produce an audit trail showing money detected at risk, intervention attempted, money recovered, and unrecoverable losses with reasons

### The 5 Leak Types

| # | Leak Type | Detection Signal | Recovery Action | Razorpay API |
|---|-----------|-----------------|-----------------|--------------|
| L1 | Authorized-not-captured | Payment status = `authorized`, age > 1hr, amount > 0 | Capture payment | `POST /v1/payments/{id}/capture` |
| L2 | Failed payments | Payment status = `failed`, error_code retryable | Retry via new payment link | `POST /v1/payment_links` |
| L3 | Uncontested disputes | Dispute status = `open`, age < contest deadline | Contest with evidence | `POST /v1/disputes/{id}/contest` |
| L4 | Stuck refunds | Refund status = `pending`, age > 48hrs | Flag for manual escalation | `GET /v1/payments/{id}/refunds` (monitor) |
| L5 | Abandoned checkouts | Order status = `attempted`, no successful payment | Send recovery payment link | `POST /v1/payment_links` |

## 4. Functional Requirements

### FR-1: Scanning Engine
- **FR-1.1**: System shall fetch all payments from Razorpay API with status filters (`authorized`, `failed`) and paginate through all results
- **FR-1.2**: System shall fetch all orders with status `attempted` (abandoned checkouts)
- **FR-1.3**: System shall fetch all disputes with status `open`
- **FR-1.4**: System shall fetch refunds for payments and filter by status `pending`
- **FR-1.5**: Each scan shall produce a `LeakBatch` containing zero or more `Leak` objects, each typed L1–L5
- **FR-1.6**: System shall respect API rate limits (Razorpay: 10 req/sec) and implement exponential backoff

### FR-2: Diagnosis Engine
- **FR-2.1**: For each Leak, system shall determine `recoverable: bool` and `recovery_action: enum`
- **FR-2.2**: For L1 (authorized-not-captured): check capture window (T+5 days for domestic). If within window → recoverable. If expired → unrecoverable with reason
- **FR-2.3**: For L2 (failed payments): classify error code as retryable (`network_error`, `gateway_error`) vs permanent (`card_declined`, `insufficient_funds`). Only retryable → recoverable
- **FR-2.4**: For L3 (disputes): check days since dispute opened. If < 7 days → contestable. If > 7 days → urgent flag. If > 30 days → unrecoverable (past contest window)
- **FR-2.5**: For L4 (stuck refunds): all flagged for manual escalation (no auto-recovery — refunds require bank-side resolution)
- **FR-2.6**: For L5 (abandoned checkouts): check if order created < 24hrs ago. If yes → send recovery link. If > 24hrs → low priority recovery

### FR-3: Intervention Engine
- **FR-3.1**: System shall execute recovery actions via Razorpay API calls
- **FR-3.2**: Each intervention shall be **bounded** — max 1 capture attempt per payment, max 1 payment link per abandoned order, max 1 contest per dispute
- **FR-3.3**: System shall implement **stopping rules**: (a) total recovery attempts per batch ≤ 50, (b) if 3 consecutive API failures → halt and alert, (c) if API returns 401 → halt immediately (auth issue)
- **FR-3.4**: Each intervention shall record: timestamp, API endpoint, request payload (redacted), response status, response body (redacted), success/failure
- **FR-3.5**: System shall NOT execute any action that moves money without explicit dry-run mode option. Default mode = `dry_run` (detect + diagnose only). `execute` mode required for actual API writes

### FR-4: Reporting Engine
- **FR-4.1**: System shall produce a `RecoveryReport` for each batch containing:
  - Total revenue at risk (sum of all leak amounts)
  - Total revenue recovered (sum of successfully intervened leaks)
  - Recovery rate (recovered / at_risk)
  - Per-leak-type breakdown
  - Full audit trail (every API call made)
  - Unrecoverable losses with reasons
- **FR-4.2**: Report shall be exportable as JSON and human-readable text
- **FR-4.3**: Report shall include evidence: the Razorpay API response that identified each leak and the response confirming recovery

### FR-5: API Server
- **FR-5.1**: System shall expose REST API endpoints for triggering scans, fetching reports, and viewing leak details
- **FR-5.2**: System shall support both sync (single scan) and async (batch scan with job ID) modes
- **FR-5.3**: API shall require `X-Razorpay-Key-Id` and `X-Razorpay-Key-Secret` headers (Test Mode keys only)

## 5. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Scan latency (100 transactions) | < 10 seconds |
| NFR-2 | API response time (all endpoints) | p95 < 200ms (excluding Razorpay API calls) |
| NFR-3 | Test coverage | ≥ 85% line coverage on engine modules |
| NFR-4 | API rate limit compliance | ≤ 8 req/sec to Razorpay (safety margin below 10/sec limit) |
| NFR-5 | Error resilience | Single leak processing failure shall not abort the batch |
| NFR-6 | Audit trail completeness | 100% of API calls logged with request/response metadata |
| NFR-7 | Security | API keys never logged, never returned in responses, stored only in memory for the duration of a scan |

## 6. Out of Scope (v1)

- Real-time webhook-based monitoring (v1 is polling-based scan)
- Frontend UI (API + CLI demo only)
- Database persistence (in-memory session state, JSON report files)
- Multi-merchant support (single merchant per scan)
- ML-based predictive leak detection (rule-based detection in v1)
- Actual money movement (Test Mode only — no real rupees)
- Email/SMS notification sending
- Subscription retry logic (v1 covers one-time payments only)

## 7. Success Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Detects all 5 leak types | 5/5 on synthetic test data | Test suite with known leak scenarios |
| Executes recovery actions via real Razorpay APIs | All 5 action types exercised against Test Mode | Integration test with test keys |
| Shows measured money recovered | Recovery report with sum of recovered amounts | Demo output |
| Compliant escalation | Stopping rules enforced, dry_run default | Test cases for each stopping rule |
| Audit trail | Every API call logged | Audit log verification in tests |
| Handles failures gracefully | No crash on malformed data, API errors | Fuzz test with bad data |
| AI does meaningful work | LLM classifies error codes, generates dispute evidence, prioritizes leaks | Remove AI → system degrades to static rules (demonstrably worse) |

## 8. AI's Role in the System

AI is the diagnostic and decision engine, not decoration:

| Task | Without AI | With AI |
|------|-----------|---------|
| Classify failed payment error codes as retryable vs permanent | Static lookup table (misses new error codes, can't handle nuances) | LLM reads error description, classifies with reasoning, handles unseen codes |
| Generate dispute contest evidence | Template with blank fields | LLM reads dispute reason + transaction data, drafts evidence submission with relevant facts |
| Prioritize leaks for recovery | FIFO ordering | LLM ranks by recoverability likelihood × amount × urgency |
| Diagnose root cause of payment degradation | "Payment failed" | LLM analyzes pattern across multiple failures, identifies gateway issues vs card issues vs network issues |
| Generate human-readable recovery report | Raw JSON dump | LLM writes executive summary with actionable insights |

**Remove AI → system becomes a brittle static rule engine that can't handle edge cases or unseen error codes.** AI is the reasoning layer that makes the agent adaptive.

## 9. Track 3 Compliance Checklist

- [x] Detects revenue at risk (5 leak types)
- [x] Determines the right intervention (diagnosis engine classifies recoverability)
- [x] Executes bounded recovery workflow (capture, retry, contest, escalate, re-engage)
- [x] Shows measured money recovered across a batch (RecoveryReport with sums)
- [x] Compliant escalation (stopping rules, dry_run default, max 50 interventions/batch)
- [x] Stopping rules (3 consecutive failures → halt, 401 → immediate halt, per-leak single attempt)
- [x] Audit trail (every API call logged with timestamp, endpoint, status, redacted payload)
- [x] Uses Razorpay Test Mode APIs (core integration, not cosmetic)
