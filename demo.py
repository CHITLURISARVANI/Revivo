"""
Reclaim — End-to-End Demo
Run: python demo.py
"""

import sys
import os
from pathlib import Path

# Windows consoles often default to cp1252 — force UTF-8 for banners/emojis
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))

from core.orchestrator import run_scan
from core.database import reset_db


def print_banner():
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║  RECLAIM — AI Revenue Recovery Agent                                 ║")
    print("║  Razorpay AI Buildathon 2026 — Track 03 (AI Revenue Recovery)        ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()


def print_engine_result(result):
    engine = result.get("engine", "unknown")
    scanned = result.get("scanned", 0)
    issues = result.get("issues_found", 0)
    recovered = result.get("amount_recovered_inr", 0)
    pending = result.get("amount_pending_inr", 0)
    escalated = result.get("escalated", 0)

    if result.get("skipped"):
        print(f"  [SKIP] {engine} — disabled")
        print()
        return

    print(f"  [{engine.upper()}] Scanned: {scanned} | Issues: {issues} | "
          f"Recovered: ₹{recovered:,.0f} | Pending: ₹{pending:,.0f} | Escalated: {escalated}")
    print()

    for issue in result.get("issues", []):
        issue_type = issue.get("issue_type", "unknown")
        amount = issue.get("amount_inr", 0)
        action = issue.get("action_taken", "none")
        entity = issue.get("razorpay_entity_id", "N/A")

        # Emoji based on result
        if issue.get("recovered"):
            emoji = "✅"
            result_text = f"RECOVERED ₹{amount:,.0f}"
        elif issue.get("pending"):
            emoji = "📤"
            result_text = f"PENDING ₹{amount:,.0f}"
        elif issue.get("escalated"):
            emoji = "⚠️"
            result_text = f"ESCALATED ₹{amount:,.0f}"
        else:
            emoji = "✋"
            result_text = f"NO ACTION ₹{amount:,.0f}"

        # AI reasoning if available
        ai_info = ""
        if issue.get("ai_classification"):
            ai_info = f" | AI: {issue['ai_classification'].upper()}"
        elif issue.get("ai_winnability_score"):
            ai_info = f" | AI winnability: {issue['ai_winnability_score']:.2f}"
        elif issue.get("ai_reasoning"):
            ai_info = f" | AI: {issue['ai_reasoning'][:60]}..."

        # Recovery message if available
        msg_info = ""
        if issue.get("recovery_message"):
            msg_info = f"\n    📝 Msg: \"{issue['recovery_message'][:80]}...\""
        if issue.get("recovery_link"):
            msg_info += f"\n    🔗 Link: {issue['recovery_link']}"

        print(f"    {emoji} {entity} | {issue_type} | {action} | {result_text}{ai_info}{msg_info}")

    print()


def main():
    print_banner()

    # Reset DB for clean demo
    print("Resetting database for clean demo...")
    reset_db()
    print()

    # Check mode
    razorpay_key = os.getenv("RAZORPAY_KEY_ID")
    openai_key = os.getenv("OPENAI_API_KEY")

    mode_parts = []
    mode_parts.append("Razorpay: " + ("LIVE TEST MODE" if razorpay_key else "SIMULATED"))
    mode_parts.append("AI: " + ("LLM (gpt-4o-mini)" if openai_key else "RULES-BASED FALLBACK"))
    print(f"  Mode: {' | '.join(mode_parts)}")
    print()

    print("Scanning all Razorpay data across 5 engines...")
    print("─" * 70)
    print()

    # Run the scan
    result = run_scan()

    # Print each engine's results
    engine_names = {
        "capture_guardian": "CAPTURE GUARDIAN",
        "retry_strategist": "RETRY STRATEGIST",
        "dispute_defender": "DISPUTE DEFENDER",
        "refund_resolver": "REFUND RESOLVER",
        "checkout_rescuer": "CHECKOUT RESCUER",
    }

    for engine_result in result.get("engines", []):
        engine_key = engine_result.get("engine", "")
        name = engine_names.get(engine_key, engine_key.upper())
        print(f"[{name}]")
        print_engine_result(engine_result)

    # Print summary
    summary = result.get("summary", {})
    print("═" * 70)
    print("  SCAN COMPLETE")
    print("═" * 70)
    print()
    print(f"  Payments scanned:    {summary.get('payments_scanned', 0)}")
    print(f"  Issues found:        {summary.get('issues_found', 0)}")
    print(f"  Amount at risk:      ₹{summary.get('amount_at_risk_inr', 0):,.2f}")
    print(f"  Amount recovered:    ₹{summary.get('amount_recovered_inr', 0):,.2f} (confirmed)")
    print(f"  Pending recovery:    ₹{summary.get('amount_pending_inr', 0):,.2f} (links sent)")
    print(f"  Escalated:           {summary.get('escalations', 0)} (needs human review)")
    print()
    print(f"  Razorpay mode:       {result.get('razorpay_mode', 'unknown')}")
    print(f"  Scan run ID:         {result.get('scan_run_id', 'N/A')}")
    print()
    print("═" * 70)
    print("  Audit trail logged. Every action is traceable.")
    print("  Dashboard: python server.py → http://localhost:8000/dashboard")
    print("═" * 70)
    print()
    print("  Reclaim — \"Payout.app found money consumers didn't know they were owed.")
    print("  We built the same thing for merchants — and autonomously recover it.")
    print("  Through Razorpay APIs. Within bounds. With full audit trail.\"")
    print()


if __name__ == "__main__":
    main()
