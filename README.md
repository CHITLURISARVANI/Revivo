# Revivo — AI Revenue Recovery Agent

> **Payout.app found money consumers didn't know they were owed. Revivo finds money merchants don't know they're losing — and autonomously recovers it through Razorpay APIs.**
>
> Built for Razorpay AI Buildathon 2026 — Track 03 (AI Revenue Recovery)

## The Problem

Merchants lose 1-3% of gross revenue to 5 silent leaks they never check:

1. **Authorized, Never Captured** — Payment authorized but webhook down → auto-refunded after 3 days
2. **Failed Payments, Never Retried** — Transient failures (bank downtime) treated as permanent losses
3. **Disputes, Never Contested** — Merchant has delivery proof but misses the 37-day contest window
4. **Stuck Refunds** — Customer's card expired, refund pending 21 days, customer chargebacks in frustration
5. **Abandoned Checkouts** — Customer entered email + phone, closed tab, nobody followed up

## The Solution

Revivo is an AI agent with 5 engines that plugs into a merchant's Razorpay account and autonomously:

1. **Detects** revenue at risk by scanning payments, disputes, refunds, and orders
2. **Diagnoses** root causes using AI (transient vs permanent failure, dispute winnability)
3. **Decides** the right intervention within merchant-set boundaries
4. **Executes** recovery actions through Razorpay APIs (capture, retry link, contest, instant refund)
5. **Reports** measured money recovered with a full append-only audit trail

## 5 Recovery Engines

| Engine | Leak Target | Razorpay APIs |
|---|---|---|
| Capture Guardian | Authorized-not-captured | `GET /payments`, `POST /payments/{id}/capture` |
| Retry Strategist | Failed payments | `GET /payments`, `POST /payment_links` |
| Dispute Defender | Uncontested disputes | `GET /disputes`, `PATCH /disputes/{id}/contest` |
| Refund Resolver | Stuck refunds | `GET /refunds`, `POST /refunds` |
| Checkout Rescuer | Abandoned checkouts | `GET /orders`, `POST /payment_links` |

## AI Reasoning Layer

| Function | Purpose | Fallback |
|---|---|---|
| `classify_failure()` | Classify payment failure as transient/permanent/ambiguous | Rules-based error code matching |
| `score_dispute_winnability()` | Score 0.0-1.0 how winnable a dispute is | Rules-based on dispute reason + evidence |
| `generate_dispute_evidence()` | Generate structured contest evidence | Template-based evidence |
| `generate_recovery_message()` | Generate personalized Hinglish recovery SMS | Template-based message |

Every AI function has a rules-based fallback. The demo works without an OpenAI API key.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Seed synthetic demo data (50 entities, all 5 leak types)
python scripts/seed_test_data.py

# Run the CLI demo (works without API keys — uses simulated data + rules-based AI)
python demo.py

# Start the website (landing + live demo workspace)
python server.py
# Open http://localhost:8000
# Click "Scan Razorpay" for the 5-minute demo flow

# Run tests
python -m pytest -v

# Or use the API
curl http://localhost:8000/
curl -X POST http://localhost:8000/api/scan
curl http://localhost:8000/api/dashboard
curl http://localhost:8000/api/issues
curl http://localhost:8000/api/escalations
```

## Configuration

Create a `.env` file (optional — demo works without it):

```
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
OPENAI_API_KEY=your_openai_key
```

- **Razorpay keys**: Get from https://dashboard.razorpay.com/app/keys (test mode, free)
- **OpenAI key**: Get from https://platform.openai.com (optional — fallback works without it)

## Merchant Boundaries

Every action is bounded by merchant-set rules in `data/boundaries.json`:

| Rule | Default |
|---|---|
| Auto-capture threshold | ₹50,000 |
| Max retries per payment | 2 |
| Auto-contest dispute threshold | ₹25,000 |
| Never auto-contest | Fraud category |
| Auto-reissue refund threshold | ₹10,000 |
| Min abandoned order for recovery | ₹500 |

Actions above thresholds are escalated to the merchant. Never executed autonomously.

## Architecture

```
Merchant Dashboard → FastAPI → Orchestrator
                                ├── Engine 1: Capture Guardian
                                ├── Engine 2: Retry Strategist
                                ├── Engine 3: Dispute Defender
                                ├── Engine 4: Refund Resolver
                                ├── Engine 5: Checkout Rescuer
                                ├── AI Reasoning Layer (LLM + fallback)
                                ├── Boundary Enforcer (guardrails)
                                ├── Audit Logger (append-only)
                                └── Razorpay Client → Razorpay API
```

## Track 03 Compliance

- ✅ Detect revenue at risk → 5 engines scan payments, disputes, refunds, orders
- ✅ Determine right intervention → AI diagnoses root cause per case
- ✅ Execute bounded recovery → within merchant thresholds
- ✅ Show measured money recovered → demo shows recovered amount across batch
- ✅ Compliant escalation → above-threshold actions to human review
- ✅ Stopping rules → max retries, max messages, no auto-contest above threshold
- ✅ Audit trail → append-only, every action logged with plain-English explanation

## The One-Liner

> **"Payout.app found money consumers didn't know they were owed. Revivo finds money merchants don't know they're losing — and autonomously recovers it through Razorpay APIs."**

## Tech Stack

- Python 3.11 + FastAPI
- Razorpay Python SDK
- OpenAI API (gpt-4o-mini) with rules-based fallback
- SQLite (audit ledger)
- Vanilla HTML/JS/CSS dashboard

## License

MIT
