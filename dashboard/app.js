// Reclaim app — clear views, one job each

const SESSION_KEY = "reclaim_session";

const ENGINE_NAMES = {
    capture_guardian: "Capture Guardian",
    retry_strategist: "Retry Strategist",
    dispute_defender: "Dispute Defender",
    refund_resolver: "Refund Resolver",
    checkout_rescuer: "Checkout Rescuer",
};

const PAGE_META = {
    home: {
        title: "Home",
        desc: "Welcome — recover revenue leaking from your Razorpay account.",
    },
    scan: {
        title: "Run scan",
        desc: "One click. Five engines. Clear results.",
    },
    issues: {
        title: "Issues",
        desc: "Everything found and what Reclaim did.",
    },
    escalations: {
        title: "Escalations",
        desc: "Above your limits — waiting for your decision.",
    },
    audit: {
        title: "Audit trail",
        desc: "Full history of every automated action.",
    },
    architecture: {
        title: "Architecture",
        desc: "How the system is built — simple and bounded.",
    },
    rules: {
        title: "Your rules",
        desc: "Merchant boundaries that block unsafe auto-actions.",
    },
};

let lastScan = null;

function getSession() {
    try {
        return JSON.parse(localStorage.getItem(SESSION_KEY) || "null");
    } catch {
        return null;
    }
}

function saveSession(session) {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

function clearSession() {
    localStorage.removeItem(SESSION_KEY);
}

function showAuthStep(step) {
    ["auth-choice", "auth-razorpay", "auth-signup"].forEach((id) => {
        document.getElementById(id)?.classList.add("hidden");
    });
    document.getElementById(step)?.classList.remove("hidden");
}

function enterApp(session) {
    saveSession(session);
    document.getElementById("auth-gate")?.classList.add("hidden");
    document.getElementById("app-shell")?.classList.remove("hidden");
    setText("merchant-name", session.businessName || session.email || "Merchant");
    showView("home");
    initAppData();
}

function showAuthGate() {
    document.getElementById("app-shell")?.classList.add("hidden");
    document.getElementById("auth-gate")?.classList.remove("hidden");
    showAuthStep("auth-choice");
}

function connectRazorpay(demo) {
    const keyId = document.getElementById("rzp-key-id")?.value.trim();
    const keySecret = document.getElementById("rzp-key-secret")?.value.trim();
    const existing = getSession() || {};

    if (!demo && (!keyId || !keySecret)) {
        alert("Enter both Key ID and Key Secret, or choose Continue with demo data.");
        return;
    }

    enterApp({
        ...existing,
        method: demo ? "demo" : "razorpay",
        businessName: existing.businessName || (demo ? "Demo Merchant" : "Razorpay Merchant"),
        email: existing.email || "",
        razorpayConnected: true,
        demoMode: !!demo,
        // Demo only — never send secrets to a real backend from the browser in production
        keyId: demo ? null : keyId,
        connectedAt: new Date().toISOString(),
    });
}

function createAccount() {
    const name = document.getElementById("su-name")?.value.trim();
    const email = document.getElementById("su-email")?.value.trim();
    const pass = document.getElementById("su-pass")?.value;

    if (!name || !email || !pass || pass.length < 6) {
        alert("Enter business name, email, and a password (min 6 characters).");
        return;
    }

    saveSession({
        method: "signup",
        businessName: name,
        email,
        razorpayConnected: false,
        demoMode: false,
        createdAt: new Date().toISOString(),
    });

    // After signup, still must connect Razorpay
    showAuthStep("auth-razorpay");
    document.querySelector("#auth-razorpay .auth-lead").textContent =
        "Account created for " + name + ". Now connect Razorpay (or use demo data).";
}

function formatINR(amount) {
    if (amount == null || amount === "") return "₹0";
    return "₹" + Number(amount).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatTime(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleTimeString("en-IN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    });
}

function badge(issue) {
    if (issue.recovered) return '<span class="badge badge-success">RECOVERED</span>';
    if (issue.pending) return '<span class="badge badge-pending">PENDING</span>';
    if (issue.escalated) return '<span class="badge badge-escalated">ESCALATED</span>';
    return '<span class="badge badge-none">NO ACTION</span>';
}

function showView(name) {
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));

    const view = document.getElementById("view-" + name);
    const nav = document.querySelector('.nav-item[data-view="' + name + '"]');
    if (view) view.classList.add("active");
    if (nav) nav.classList.add("active");

    const meta = PAGE_META[name] || PAGE_META.home;
    document.getElementById("page-title").textContent = meta.title;
    document.getElementById("page-desc").textContent = meta.desc;

    document.querySelector(".sidebar")?.classList.remove("open");
    window.scrollTo({ top: 0, behavior: "smooth" });
}

function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
}

async function animateSteps() {
    const steps = document.querySelectorAll("#loading-steps li");
    steps.forEach((li) => li.classList.remove("active", "done"));
    for (const li of steps) {
        li.classList.add("active");
        await sleep(260);
        li.classList.remove("active");
        li.classList.add("done");
    }
}

async function runScan() {
    showView("scan");
    document.getElementById("scan-results")?.classList.add("hidden");
    document.getElementById("loading")?.classList.remove("hidden");

    ["scan-btn", "scan-btn-main", "home-scan-btn"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = true;
    });

    animateSteps();

    try {
        const res = await fetch("/api/scan", { method: "POST" });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        await sleep(300);
        lastScan = data;
        renderAll(data);
        document.getElementById("loading")?.classList.add("hidden");
        document.getElementById("scan-results")?.classList.remove("hidden");
    } catch (err) {
        alert("Scan failed: " + err.message);
        document.getElementById("loading")?.classList.add("hidden");
    } finally {
        ["scan-btn", "scan-btn-main", "home-scan-btn"].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.disabled = false;
        });
    }
}

function renderAll(data) {
    const s = data.summary || {};

    // Home + scan stats
    setText("home-recovered", formatINR(s.amount_recovered_inr));
    setText("home-at-risk", formatINR(s.amount_at_risk_inr));
    setText("home-pending", formatINR(s.amount_pending_inr));
    setText("home-escalated", s.escalations || 0);

    setText("stat-scanned", s.payments_scanned || 0);
    setText("stat-issues", s.issues_found || 0);
    setText("stat-recovered", formatINR(s.amount_recovered_inr));
    setText("stat-pending", formatINR(s.amount_pending_inr));
    setText("stat-escalated", s.escalations || 0);

    renderEngines(data.engines || []);
    renderIssues(data.engines || []);
    renderEscalations(data.engines || []);
    loadAudit(data.scan_run_id);

    const mode =
        data.razorpay_mode === "simulated"
            ? "Mode: Simulated (demo)"
            : "Mode: Live test";
    setText("mode-indicator", mode);
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function renderEngines(engines) {
    const body = document.getElementById("engines-body");
    if (!body) return;
    body.innerHTML = "";

    engines.forEach((er) => {
        if (er.skipped) return;
        const recovered = er.amount_recovered_inr || 0;
        const pending = er.amount_pending_inr || 0;
        const total = recovered + pending;
        const row = document.createElement("div");
        row.className = "engine-row";
        row.innerHTML = `
            <strong>${ENGINE_NAMES[er.engine] || er.engine}</strong>
            <span class="meta">Scanned ${er.scanned || 0} · Issues ${er.issues_found || 0}${er.escalated ? " · Escalated " + er.escalated : ""}</span>
            <span class="amt ${total ? "" : "zero"}">${total ? formatINR(total) : "—"}</span>
        `;
        body.appendChild(row);
    });
}

function renderIssues(engines) {
    const tbody = document.getElementById("issues-body");
    const empty = document.getElementById("issues-empty");
    const wrap = document.getElementById("issues-wrap");
    if (!tbody) return;

    tbody.innerHTML = "";
    let count = 0;

    for (const er of engines) {
        if (er.skipped) continue;
        for (const issue of er.issues || []) {
            count++;
            const ai = [];
            if (issue.ai_classification) ai.push(issue.ai_classification.toUpperCase());
            if (issue.ai_winnability_score != null) {
                ai.push("win " + Number(issue.ai_winnability_score).toFixed(2));
            }
            if (issue.ai_reasoning) ai.push(String(issue.ai_reasoning).slice(0, 90) + "…");
            if (issue.recovery_message) {
                ai.push('"' + String(issue.recovery_message).slice(0, 60) + '…"');
            }

            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${ENGINE_NAMES[issue.engine] || issue.engine || ""}</td>
                <td>${issue.issue_type || ""}</td>
                <td><code>${issue.razorpay_entity_id || issue.payment_id || "—"}</code></td>
                <td>${formatINR(issue.amount_inr)}</td>
                <td>${issue.action_taken || "—"}</td>
                <td>${badge(issue)}</td>
                <td class="ai-cell">${ai.join(" · ") || "—"}</td>
            `;
            tbody.appendChild(tr);
        }
    }

    if (count) {
        empty?.classList.add("hidden");
        wrap?.classList.remove("hidden");
    } else {
        empty?.classList.remove("hidden");
        wrap?.classList.add("hidden");
    }
}

function renderEscalations(engines) {
    const body = document.getElementById("escalations-body");
    if (!body) return;
    body.innerHTML = "";
    let count = 0;

    for (const er of engines) {
        for (const issue of er.issues || []) {
            if (!issue.escalated) continue;
            count++;
            const div = document.createElement("div");
            div.className = "esc-item";
            div.innerHTML = `
                <div>
                    <strong>${ENGINE_NAMES[issue.engine] || issue.engine}</strong>
                    <p>${issue.reason || issue.action_taken || "Needs review"} · ${issue.razorpay_entity_id || issue.payment_id || ""}</p>
                </div>
                <span class="esc-amt">${formatINR(issue.amount_inr)}</span>
            `;
            body.appendChild(div);
        }
    }

    if (!count) {
        body.innerHTML = '<p class="muted" id="escalations-empty">None yet. Run a scan first.</p>';
    }
}

async function loadAudit(scanRunId) {
    const trail = document.getElementById("audit-trail");
    if (!trail || !scanRunId) return;

    try {
        const res = await fetch("/api/audit/" + scanRunId);
        const data = await res.json();
        trail.innerHTML = "";

        const entries = data.entries || [];
        if (!entries.length) {
            trail.innerHTML = '<p class="muted" id="audit-empty">No audit entries yet. Run a scan first.</p>';
            return;
        }

        for (const entry of entries) {
            const div = document.createElement("div");
            div.className = "audit-entry " + (entry.phase || "");
            div.innerHTML = `
                <span class="audit-time">${formatTime(entry.timestamp)}</span>
                <span class="audit-engine">[${entry.engine}] ${(entry.phase || "").toUpperCase()}</span>
                <span>${entry.human_readable || ""}</span>
            `;
            trail.appendChild(div);
        }
    } catch (err) {
        console.error(err);
    }
}

async function loadRules() {
    const body = document.getElementById("rules-body");
    if (!body) return;
    try {
        const res = await fetch("/api/boundaries");
        const cfg = await res.json();
        const engines = [
            ["capture_guardian", "Capture Guardian", [
                ["Auto-capture max", "₹" + (cfg.capture_guardian?.auto_capture_threshold_inr || 0).toLocaleString("en-IN")],
                ["Min age", (cfg.capture_guardian?.min_authorized_age_hours || 0) + " hours"],
            ]],
            ["retry_strategist", "Retry Strategist", [
                ["Max retries", cfg.retry_strategist?.max_retries_per_payment],
                ["Min amount", "₹" + (cfg.retry_strategist?.retry_only_above_inr || 0)],
            ]],
            ["dispute_defender", "Dispute Defender", [
                ["Auto-contest max", "₹" + (cfg.dispute_defender?.auto_contest_threshold_inr || 0).toLocaleString("en-IN")],
                ["Never auto", (cfg.dispute_defender?.never_auto_contest_categories || []).join(", ")],
            ]],
            ["refund_resolver", "Refund Resolver", [
                ["Auto-reissue max", "₹" + (cfg.refund_resolver?.auto_reissue_threshold_inr || 0).toLocaleString("en-IN")],
                ["Min pending age", (cfg.refund_resolver?.min_pending_age_days || 0) + " days"],
            ]],
            ["checkout_rescuer", "Checkout Rescuer", [
                ["Min order", "₹" + (cfg.checkout_rescuer?.min_order_amount_inr || 0)],
                ["Max messages", cfg.checkout_rescuer?.max_recovery_messages_per_order],
            ]],
        ];

        body.innerHTML = engines
            .map(
                ([, title, rows]) => `
            <div class="rule-card">
                <h4>${title}</h4>
                <ul>${rows.map(([k, v]) => `<li><strong>${k}:</strong> ${v}</li>`).join("")}</ul>
            </div>`
            )
            .join("");
    } catch {
        body.innerHTML = '<p class="muted">Could not load rules.</p>';
    }
}

async function resetDemo() {
    if (!confirm("Clear previous scans and start fresh?")) return;
    await fetch("/api/reset", { method: "POST" });
    lastScan = null;
    setText("home-recovered", "₹0");
    setText("home-at-risk", "₹0");
    setText("home-pending", "₹0");
    setText("home-escalated", "0");
    document.getElementById("scan-results")?.classList.add("hidden");
    document.getElementById("issues-wrap")?.classList.add("hidden");
    document.getElementById("issues-empty")?.classList.remove("hidden");
    document.getElementById("escalations-body").innerHTML =
        '<p class="muted">None yet. Run a scan first.</p>';
    document.getElementById("audit-trail").innerHTML =
        '<p class="muted">No audit entries yet. Run a scan first.</p>';
    showView("home");
}

async function initAppData() {
    try {
        const h = await fetch("/health").then((r) => r.json());
        const session = getSession();
        let mode =
            h.razorpay_api === "simulated" ? "Mode: Simulated (demo)" : "Mode: Live test";
        if (session?.demoMode) mode = "Mode: Demo data";
        if (session?.keyId) mode = "Mode: Keys connected (browser)";
        setText("mode-indicator", mode);
    } catch {
        setText("mode-indicator", "Mode: offline");
    }

    loadRules();

    try {
        const dash = await fetch("/api/dashboard").then((r) => r.json());
        if (dash.has_data && dash.latest_scan) {
            const s = dash.latest_scan;
            setText("home-recovered", formatINR(s.total_amount_recovered_inr));
            setText("home-at-risk", formatINR(s.total_amount_at_risk_inr));
            setText("home-escalated", s.total_escalations || 0);
            if (s.id) loadAudit(s.id);
        }
    } catch {
        /* first visit */
    }
}

function boot() {
    const session = getSession();
    if (session?.razorpayConnected) {
        enterApp(session);
    } else {
        showAuthGate();
        if (session && !session.razorpayConnected) {
            // Created account earlier, still need Razorpay
            showAuthStep("auth-razorpay");
        }
    }
}

// Auth UI
document.getElementById("btn-razorpay-path")?.addEventListener("click", () => showAuthStep("auth-razorpay"));
document.getElementById("btn-signup-path")?.addEventListener("click", () => showAuthStep("auth-signup"));
document.getElementById("back-from-rzp")?.addEventListener("click", () => showAuthStep("auth-choice"));
document.getElementById("back-from-signup")?.addEventListener("click", () => showAuthStep("auth-choice"));
document.getElementById("btn-connect-rzp")?.addEventListener("click", () => connectRazorpay(false));
document.getElementById("btn-demo-mode")?.addEventListener("click", () => connectRazorpay(true));
document.getElementById("btn-create-account")?.addEventListener("click", createAccount);
document.getElementById("logout-btn")?.addEventListener("click", () => {
    clearSession();
    showAuthGate();
});

// Nav
document.getElementById("sidebar-nav")?.addEventListener("click", (e) => {
    const btn = e.target.closest(".nav-item");
    if (!btn) return;
    showView(btn.dataset.view);
});

document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.goto));
});

document.getElementById("scan-btn")?.addEventListener("click", runScan);
document.getElementById("scan-btn-main")?.addEventListener("click", runScan);
document.getElementById("home-scan-btn")?.addEventListener("click", runScan);
document.getElementById("reset-btn")?.addEventListener("click", resetDemo);
document.getElementById("menu-toggle")?.addEventListener("click", () => {
    document.querySelector(".sidebar")?.classList.toggle("open");
});

boot();
