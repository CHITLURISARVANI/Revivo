# Revivo — AI Revenue Recovery Agent

> **Payout.app found money consumers didn't know they were owed. Revivo finds money merchants don't know they're losing — and recovers it autonomously through Razorpay APIs.**

**Built for Razorpay AI Buildathon 2026 — Track 03**

---

## The Problem

Merchants lose **1–3% of GMV** to five silent leaks they rarely check: authorized-but-not-captured payments, failed payments never retried, uncontested disputes, stuck refunds, and abandoned checkouts. For a merchant processing **₹50L/month**, that is **₹50,000–₹1,50,000** drained every month — not from fraud or competition, but from inattention. Dashboards show history; they don't recover the leak.

---

## Live Demo

**https://revivo-n6c0.onrender.com**

> **Cold start:** Free Render sleeps when idle. First open can take **30–60s** — the in-app wake screen covers this. For live judging, open the URL once **before** your slot so the service is warm.

**Click “Continue with demo data” → “Run scan”** to see all 5 engines detect and recover **₹75,900** across **15** simulated issues.

**Judge path after scan:** Overview (before→after) → **Escalations** (Failure Recovery) → **Audit** (proof).

---

## How It Works

An **orchestrator** runs five engines in one scan. Each issue follows: **detect → diagnose (AI where it matters) → decide (boundary check) → execute or escalate → audit log**.

```
Razorpay data
     │
     ▼
┌─────────────┐
│ Orchestrator│
└──────┬──────┘
       ├── Capture Guardian     → capture authorized payments
       ├── Retry Strategist     → retry transient failures
       ├── Dispute Defender     → contest winnable disputes
       ├── Refund Resolver      → reissue stuck refunds
       └── Checkout Rescuer     → recover abandoned checkouts
              │
              ▼
     Boundary Enforcer ──► execute  |  escalate to human
              │
              ▼
         Audit trail (append-only)
```

---

## Where AI Actually Matters

Not decoration — three places where judgment changes the action:

| Engine | AI job |
|---|---|
| **Retry Strategist** | Classifies failures as **transient vs permanent** (e.g. UPI bank outage vs insufficient funds) with a confidence score |
| **Dispute Defender** | Scores **dispute winnability** from evidence and builds structured contest packages |
| **Checkout Rescuer** | Generates personalized **Hinglish** recovery messages with payment links |

All three have a **rules-based fallback** if no OpenAI key is set — the demo runs without one. With `OPENAI_API_KEY` set on Render, `/health` shows `"ai_api": "connected"` instead of `"fallback"`.

---

## Merchant Boundaries (Safety First)

Every auto-action is gated by `data/boundaries.json`. Above threshold → **escalated to a human**, never silently auto-executed.

| Engine | Guardrail |
|---|---|
| Capture Guardian | Auto-capture only below **₹50,000** |
| Retry Strategist | Max **2** retries, **30 min** gap |
| Dispute Defender | Auto-contest only below **₹25,000**; **never** auto for **fraud** |
| Refund Resolver | Auto-reissue only below **₹10,000** |
| Checkout Rescuer | Recovery only for orders ≥ **₹500** |

---

## Failure Recovery (human-in-the-loop)

Revivo is built so **auto-act never silently fails** on risky cases:

1. **Detect** the leak (authorized payment, dispute, refund, etc.)
2. **Diagnose** with AI / rules (retryable? winnable?)
3. **Decide** against merchant boundaries
4. If safe → **execute** and write an audit row  
   If amount, category, or risk exceeds rules → **escalate** to a human (no auto money move)
5. Merchant resolves the escalation; the **append-only audit trail** still records detect → diagnose → decide → escalate

**Demo proof:** after one scan you get **3 escalations** (high-value / high-risk) alongside **₹75,900** recovered. Open **Escalations** then **Audit** to see the Failure Recovery path end-to-end.

This is intentional product design for Track 03 — agents that handle money must know when **not** to act.

---

## Testing

69 automated tests cover every engine, boundary rule, AI classifier, and audit invariant — including full scan determinism (same seed → same result every run) and correct `[SIMULATED]` tagging in demo mode.

```bash
python -m pytest -v   # 69 passed
```

---

## Simulated vs Live

Demo mode uses seeded synthetic data (`scripts/seed_test_data.py`) and tags every automated action `[SIMULATED]` in the audit trail. Live mode uses real Razorpay test-mode keys via `.env` — same orchestrator, same engines, same boundary logic, no code swap needed. The `[SIMULATED]` tag disappears automatically once live keys are set.

---

## Tech Stack

| Component | Technology |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Razorpay | Official `razorpay` Python SDK |
| AI | OpenAI **gpt-4o-mini** (rules fallback) |
| Database | SQLite |
| Dashboard | HTML + Vanilla JS + CSS |
| Tests | pytest |

---

## Running Locally

```bash
git clone https://github.com/CHITLURISARVANI/Revivo.git
cd Revivo
pip install -r requirements.txt

# Optional — demo works without keys (simulated Razorpay + AI fallback)
# RAZORPAY_KEY_ID=...  RAZORPAY_KEY_SECRET=...  OPENAI_API_KEY=...

python server.py
# → http://localhost:8000
# Connect with Razorpay → Continue with demo data → Run scan
```

```bash
python -m pytest -v          # full suite
python demo.py               # CLI end-to-end scan
```

---

## Repo

**https://github.com/CHITLURISARVANI/Revivo**
