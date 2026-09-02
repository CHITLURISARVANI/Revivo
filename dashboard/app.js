// Revivo — polished SaaS dashboard interactions

const SESSION_KEY = "Revivo_session";
const SCAN_CACHE_KEY = "Revivo_last_scan";

const ENGINE_NAMES = {
    capture_guardian: "Capture Guardian",
    retry_strategist: "Retry Strategist",
    dispute_defender: "Dispute Defender",
    refund_resolver: "Refund Resolver",
    checkout_rescuer: "Checkout Rescuer",
};

const ENGINE_SHORT = {
    capture_guardian: "Capture",
    retry_strategist: "Retry",
    dispute_defender: "Dispute",
    refund_resolver: "Refund",
    checkout_rescuer: "Checkout",
};

const PAGE_META = {
    home: { title: "Overview", desc: "Problem → insight → action → result" },
    scan: { title: "Scan", desc: "Run the recovery agent across five engines" },
    insights: { title: "Insights", desc: "Charts and funnel for recovered revenue" },
    issues: { title: "Issues", desc: "Every leak found and the action taken" },
    escalations: { title: "Escalations", desc: "Needs a human — above your auto limits" },
    audit: { title: "Audit", desc: "Append-only trail of every decision" },
    architecture: { title: "Architecture", desc: "How Revivo is wired" },
    rules: { title: "Rules", desc: "Merchant boundaries that keep actions safe" },
};

const COLORS = {
    recover: "#0f8a4b",
    pending: "#9a6a0a",
    risk: "#c2452d",
    brand: "#0b3f34",
    muted: "#8aa399",
};

const RECOVERY_ETA = {
    capture_guardian: {
        kicker: "Capture Guardian",
        headline: "Usually minutes",
        range: "1–30 min",
        speed: 92,
        speedLabel: "Very fast",
        note: "Fastest path — the payment was already authorized on Razorpay.",
        steps: [
            "Detect authorized-but-not-captured payments",
            "Auto-capture within your merchant rules",
            "Funds settle to the merchant account",
        ],
        window: "Window: act inside Razorpay’s capture deadline (~5 days)",
    },
    retry_strategist: {
        kicker: "Retry Strategist",
        headline: "Minutes to a few hours",
        range: "5 min – 6 hrs",
        speed: 78,
        speedLabel: "Fast",
        note: "AI retries only transient failures — permanent declines are skipped.",
        steps: [
            "Classify failure as retryable vs permanent",
            "Retry with smart timing / channel",
            "Confirm success or stop to avoid fees",
        ],
        window: "Window: best within hours of the original failure",
    },
    dispute_defender: {
        kicker: "Dispute Defender",
        headline: "Days to a few weeks",
        range: "3–21 days",
        speed: 28,
        speedLabel: "Slower (network process)",
        note: "Evidence goes out fast; final outcome depends on the card network.",
        steps: [
            "Pull transaction + delivery evidence",
            "Contest the dispute via Razorpay",
            "Wait for issuer / network decision",
        ],
        window: "Window: contest before the dispute deadline (often ~7–30 days)",
    },
    refund_resolver: {
        kicker: "Refund Resolver",
        headline: "Hours to a couple of days",
        range: "2 hrs – 2 days",
        speed: 55,
        speedLabel: "Moderate",
        note: "Clears stuck refunds so they don’t turn into chargebacks.",
        steps: [
            "Find refunds stuck pending too long",
            "Resolve or escalate within rules",
            "Customer gets funds; dispute risk drops",
        ],
        window: "Window: act before the customer files a chargeback",
    },
    checkout_rescuer: {
        kicker: "Checkout Rescuer",
        headline: "Minutes to 24 hours",
        range: "5 min – 24 hrs",
        speed: 68,
        speedLabel: "Fast if customer responds",
        note: "Recovery link is sent quickly; money returns when the buyer pays.",
        steps: [
            "Detect abandoned checkout with contact info",
            "Send personalized recovery payment link",
            "Capture payment when the customer completes",
        ],
        window: "Window: best within 24–72 hours of abandon",
    },
};

let lastScan = null;
const charts = {};

function refreshIcons(scope) {
    if (window.lucide?.createIcons) {
        window.lucide.createIcons({
            attrs: { "stroke-width": 1.75 },
            nameAttr: "data-lucide",
            root: scope || document.body,
        });
    }
}

function toast(message, type) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.className = "toast show" + (type ? " " + type : "");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("show"), 2800);
}

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

function cacheScan(data) {
    try {
        localStorage.setItem(SCAN_CACHE_KEY, JSON.stringify(data));
    } catch {
        /* ignore */
    }
}

function loadCachedScan() {
    try {
        return JSON.parse(localStorage.getItem(SCAN_CACHE_KEY) || "null");
    } catch {
        return null;
    }
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function formatINR(amount) {
    if (amount == null || amount === "") return "₹0";
    return "₹" + Number(amount).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatNum(amount) {
    return Number(amount || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
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

function resultLabel(issue) {
    const raw = (issue.action_result || "").toString().toLowerCase();
    if (raw) return raw;
    if (issue.recovered) return "success";
    if (issue.pending) return "pending";
    if (issue.escalated) return "escalated";
    return "no_action";
}

function aiCell(issue) {
    const parts = [];
    if (issue.ai_classification) {
        const conf =
            issue.ai_confidence != null
                ? ` ${Math.round(Number(issue.ai_confidence) * 100)}%`
                : "";
        parts.push(String(issue.ai_classification).toUpperCase() + conf);
    }
    if (issue.ai_winnability_score != null && issue.ai_winnability_score !== "") {
        const score = Number(issue.ai_winnability_score);
        parts.push(score.toFixed(2) + (score >= 0.6 ? " winnable" : " low-win"));
    }
    if (issue.evidence_summary) {
        parts.push(String(issue.evidence_summary).slice(0, 70));
    }
    if (issue.ai_reasoning) {
        parts.push(String(issue.ai_reasoning).slice(0, 100) + (String(issue.ai_reasoning).length > 100 ? "…" : ""));
    }
    if (issue.recovery_message) {
        parts.push('"' + String(issue.recovery_message).slice(0, 70) + (String(issue.recovery_message).length > 70 ? "…" : "") + '"');
    }
    if (issue.diagnosis && !parts.length) {
        parts.push(String(issue.diagnosis));
    }
    // Deterministic Capture Guardian with no AI fields → em dash
    return parts.length ? parts.join(" — ") : "—";
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
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${ENGINE_NAMES[issue.engine] || issue.engine || ""}</td>
                <td>${issue.issue_type || ""}</td>
                <td><code>${issue.razorpay_entity_id || issue.payment_id || "—"}</code></td>
                <td>${formatINR(issue.amount_inr)}</td>
                <td>${issue.action_taken || "—"}</td>
                <td class="result-cell">${badge(issue)}<div class="result-text">${resultLabel(issue)}</div></td>
                <td class="ai-cell">${aiCell(issue)}</td>
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

function showAuthStep(step) {
    ["auth-choice", "auth-razorpay", "auth-signup"].forEach((id) => {
        document.getElementById(id)?.classList.add("hidden");
    });
    document.getElementById(step)?.classList.remove("hidden");
    refreshIcons();
}

function showCinematic() {
    document.getElementById("cinematic")?.classList.remove("hidden");
    document.getElementById("auth-layout")?.classList.add("hidden");
    refreshIcons(document.getElementById("cinematic"));
}

function enterConnectFlow(step) {
    document.getElementById("cinematic")?.classList.add("hidden");
    document.getElementById("auth-layout")?.classList.remove("hidden");
    showAuthStep(step || "auth-choice");
    window.scrollTo({ top: 0, behavior: "smooth" });
}

async function ensureServerAwake() {
    const gate = document.getElementById("wake-gate");
    const fill = document.getElementById("wake-fill");
    const fine = document.getElementById("wake-fine");
    const copy = document.getElementById("wake-copy");
    const track = gate?.querySelector(".wake-track");

    const started = Date.now();
    let pct = 8;
    let timer = null;

    const bump = (next, msg) => {
        pct = Math.max(pct, next);
        if (fill) fill.style.width = pct + "%";
        if (track) track.setAttribute("aria-valuenow", String(pct));
        if (msg && fine) fine.textContent = msg;
    };

    const quick = async () => {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 2500);
        try {
            const res = await fetch("/health", { signal: ctrl.signal, cache: "no-store" });
            clearTimeout(t);
            return res.ok;
        } catch {
            clearTimeout(t);
            return false;
        }
    };

    if (await quick()) return true;

    gate?.classList.remove("hidden");
    bump(12, "Initializing engines…");
    timer = setInterval(() => {
        const elapsed = Date.now() - started;
        const target = Math.min(92, 12 + Math.floor(elapsed / 450));
        bump(target);
        if (elapsed > 12000 && copy) {
            copy.textContent = "Almost ready — preparing your recovery workspace.";
        }
        if (elapsed > 25000 && fine) {
            fine.textContent = "Finalizing secure session…";
        }
    }, 400);

    const deadline = Date.now() + 90000;
    let ok = false;
    while (Date.now() < deadline) {
        await sleep(1800);
        try {
            const res = await fetch("/health", { cache: "no-store" });
            if (res.ok) {
                ok = true;
                bump(100, "Online — loading Revivo");
                break;
            }
            bump(pct + 2, "Warming recovery engines…");
        } catch {
            bump(pct + 1, "Reconnecting workspace…");
        }
    }

    clearInterval(timer);
    await sleep(350);
    gate?.classList.add("hidden");
    if (!ok) {
        toast("Taking longer than usual — refresh once", "err");
    }
    return ok;
}

function enterApp(session) {
    saveSession(session);
    document.getElementById("wake-gate")?.classList.add("hidden");
    document.getElementById("auth-gate")?.classList.add("hidden");
    document.getElementById("app-shell")?.classList.remove("hidden");
    const name = session.businessName || session.email || "Merchant";
    setText("merchant-name", name);
    setText("merchant-avatar", (name[0] || "M").toUpperCase());
    showView("home");
    initAppData();
    refreshIcons();
    toast("Welcome back, " + name, "ok");
}

function showAuthGate() {
    document.getElementById("app-shell")?.classList.add("hidden");
    document.getElementById("auth-gate")?.classList.remove("hidden");
    document.querySelector(".sidebar")?.classList.remove("open");
    document.getElementById("sidebar-backdrop")?.classList.remove("show");
    showCinematic();
}

function connectRazorpay(demo) {
    const keyId = document.getElementById("rzp-key-id")?.value.trim();
    const keySecret = document.getElementById("rzp-key-secret")?.value.trim();
    const existing = getSession() || {};

    if (!demo && (!keyId || !keySecret)) {
        toast("Enter Key ID + Secret, or use demo data", "err");
        return;
    }

    const session = {
        ...existing,
        method: demo ? "demo" : "razorpay",
        businessName: existing.businessName || (demo ? "Demo Merchant" : "Razorpay Merchant"),
        email: existing.email || "",
        razorpayConnected: true,
        demoMode: !!demo,
        keyId: demo ? null : keyId,
        connectedAt: new Date().toISOString(),
    };

    enterApp(session);

    if (demo) {
        bootstrapDemoSession();
    }
}

async function bootstrapDemoSession() {
    toast("Loading demo dataset…");
    try {
        await fetch("/api/reset", { method: "POST" });
        const seedRes = await fetch("/api/seed", { method: "POST" });
        if (!seedRes.ok) throw new Error("seed HTTP " + seedRes.status);
        const seed = await seedRes.json();
        localStorage.removeItem(SCAN_CACHE_KEY);
        lastScan = null;
        clearOverviewMetrics();
        toast(
            `Demo ready · ${seed.counts?.payments || 0} payments — click Run scan`,
            "ok"
        );
    } catch (err) {
        toast("Demo seed failed: " + err.message + " — try Run scan", "err");
    }
}

function updateMoneyStory(summary) {
    const atRisk = Number(summary?.amount_at_risk_inr || 0);
    const recovered = Number(summary?.amount_recovered_inr || 0);
    const el = document.getElementById("money-story");
    const fill = document.getElementById("money-story-bar-fill");
    setText("story-at-risk", formatINR(atRisk));
    setText("story-recovered", formatINR(recovered));
    if (atRisk > 0 || recovered > 0) {
        setText(
            "money-story-caption",
            `${formatINR(atRisk)} at risk → ${formatINR(recovered)} recovered in one scan`
        );
        el?.classList.add("is-live");
        if (fill) {
            const pct = atRisk > 0 ? Math.min(100, Math.round((recovered / atRisk) * 100)) : 0;
            fill.style.width = pct + "%";
        }
    } else {
        setText("money-story-caption", "Run a scan to see at-risk money become recovered revenue");
        el?.classList.remove("is-live");
        if (fill) fill.style.width = "0%";
    }
}

function clearOverviewMetrics() {
    lastScan = null;
    setText("home-recovered", "₹0");
    setText("home-at-risk", "₹0");
    setText("home-pending", "₹0");
    setText("home-escalated", "0");
    setText("home-rate", "0%");
    setText("home-rate-line", "Run a scan to measure recovery");
    updateMoneyStory({});
    const badge = document.getElementById("nav-esc-badge");
    if (badge) {
        badge.textContent = "0";
        badge.dataset.count = "0";
    }
    document.getElementById("scan-results")?.classList.add("hidden");
    document.getElementById("issues-wrap")?.classList.add("hidden");
    document.getElementById("issues-empty")?.classList.remove("hidden");
    document.getElementById("insights-empty")?.classList.remove("hidden");
    document.getElementById("insights-body")?.classList.add("hidden");
    updateStoryRail(false);
}

function createAccount() {
    const name = document.getElementById("su-name")?.value.trim();
    const email = document.getElementById("su-email")?.value.trim();
    const pass = document.getElementById("su-pass")?.value;

    if (!name || !email || !pass || pass.length < 6) {
        toast("Fill business name, email, and password (6+)", "err");
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

    showAuthStep("auth-razorpay");
    const lead = document.querySelector("#auth-razorpay .lead");
    if (lead) lead.textContent = "Account ready for " + name + ". Connect Razorpay or use demo data.";
    toast("Account created — connect Razorpay next", "ok");
}

function updateStoryRail(hasScan) {
    const insight = document.getElementById("story-insight");
    const action = document.getElementById("story-action");
    const result = document.getElementById("story-result");
    [insight, action, result].forEach((el) => el?.classList.remove("active", "done"));
    if (!hasScan) {
        action?.classList.add("active");
        return;
    }
    insight?.classList.add("done");
    action?.classList.add("done");
    result?.classList.add("active");
}

function showView(name) {
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));

    document.getElementById("view-" + name)?.classList.add("active");
    document.querySelector('.nav-item[data-view="' + name + '"]')?.classList.add("active");

    const meta = PAGE_META[name] || PAGE_META.home;
    setText("page-title", meta.title);
    setText("page-desc", meta.desc);

    document.querySelector(".sidebar")?.classList.remove("open");
    document.getElementById("sidebar-backdrop")?.classList.remove("show");
    window.scrollTo({ top: 0, behavior: "smooth" });
    refreshIcons();

    if ((name === "insights" || name === "home" || name === "scan") && lastScan) {
        setTimeout(() => updateAllCharts(lastScan), 40);
    }
    if (name === "rules") {
        loadRules();
    }
}

function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
}

function animateValue(el, end, prefix, duration) {
    if (!el) return;
    const t0 = performance.now();
    function frame(t) {
        const p = Math.min(1, (t - t0) / duration);
        const eased = 1 - Math.pow(1 - p, 3);
        const val = end * eased;
        el.textContent = (prefix || "") + Math.round(val).toLocaleString("en-IN");
        if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
}

async function animateSteps() {
    const steps = document.querySelectorAll("#loading-steps li");
    steps.forEach((li) => li.classList.remove("active", "done"));
    for (const li of steps) {
        li.classList.add("active");
        await sleep(280);
        li.classList.remove("active");
        li.classList.add("done");
    }
}

function destroyChart(key) {
    if (charts[key]) {
        charts[key].destroy();
        delete charts[key];
    }
}

function upsertChart(key, canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === "undefined") return;
    destroyChart(key);
    charts[key] = new Chart(canvas, config);
}

function moneySplit(summary) {
    const recovered = Number(summary.amount_recovered_inr || 0);
    const pending = Number(summary.amount_pending_inr || 0);
    const atRisk = Number(summary.amount_at_risk_inr || 0);
    const remaining = Math.max(0, atRisk - recovered - pending);
    return { recovered, pending, remaining, atRisk };
}

function engineSeries(engines) {
    const labels = [];
    const recovered = [];
    const pending = [];
    (engines || []).forEach((er) => {
        if (er.skipped) return;
        labels.push(ENGINE_SHORT[er.engine] || er.engine);
        recovered.push(er.amount_recovered_inr || 0);
        pending.push(er.amount_pending_inr || 0);
    });
    return { labels, recovered, pending };
}

function outcomeCounts(engines) {
    let recovered = 0;
    let pending = 0;
    let escalated = 0;
    let none = 0;
    for (const er of engines || []) {
        for (const issue of er.issues || []) {
            if (issue.recovered) recovered++;
            else if (issue.pending) pending++;
            else if (issue.escalated) escalated++;
            else none++;
        }
    }
    return { recovered, pending, escalated, none };
}

function chartDefaults() {
    if (typeof Chart === "undefined") return;
    Chart.defaults.font.family = "Plus Jakarta Sans";
    Chart.defaults.color = "#4d635b";
}

function updateAllCharts(data) {
    if (!data || typeof Chart === "undefined") return;
    chartDefaults();

    const s = data.summary || {};
    const split = moneySplit(s);
    const series = engineSeries(data.engines || []);
    const outcomes = outcomeCounts(data.engines || []);

    const donutData = {
        labels: ["Recovered", "Pending", "Still at risk"],
        datasets: [
            {
                data: [split.recovered, split.pending, split.remaining],
                backgroundColor: [COLORS.recover, COLORS.pending, COLORS.risk],
                borderWidth: 0,
                hoverOffset: 8,
            },
        ],
    };
    const donutOpts = {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "64%",
        plugins: {
            legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true } },
            tooltip: { callbacks: { label: (c) => " " + formatINR(c.raw) } },
        },
    };

    upsertChart("homeDonut", "home-donut", { type: "doughnut", data: donutData, options: donutOpts });
    upsertChart("scanDonut", "scan-donut", { type: "doughnut", data: donutData, options: donutOpts });
    upsertChart("insDonut", "ins-donut", { type: "doughnut", data: donutData, options: donutOpts });

    const barData = {
        labels: series.labels,
        datasets: [
            { label: "Recovered", data: series.recovered, backgroundColor: COLORS.recover, borderRadius: 8 },
            { label: "Pending", data: series.pending, backgroundColor: COLORS.pending, borderRadius: 8 },
        ],
    };
    const barOpts = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true } },
            tooltip: {
                callbacks: {
                    label: (c) => " " + c.dataset.label + ": " + formatINR(c.raw),
                },
            },
        },
        scales: {
            x: { grid: { display: false } },
            y: {
                beginAtZero: true,
                ticks: { callback: (v) => "₹" + Number(v).toLocaleString("en-IN") },
                grid: { color: "rgba(183,201,192,0.35)" },
            },
        },
    };

    upsertChart("homeBars", "home-bars", { type: "bar", data: barData, options: barOpts });
    upsertChart("scanBars", "scan-bars", { type: "bar", data: barData, options: barOpts });
    upsertChart("insBars", "ins-bars", { type: "bar", data: barData, options: barOpts });

    upsertChart("insOutcomes", "ins-outcomes", {
        type: "bar",
        data: {
            labels: ["Recovered", "Pending", "Escalated", "No action"],
            datasets: [
                {
                    data: [outcomes.recovered, outcomes.pending, outcomes.escalated, outcomes.none],
                    backgroundColor: [COLORS.recover, COLORS.pending, COLORS.risk, COLORS.muted],
                    borderRadius: 10,
                },
            ],
        },
        options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { beginAtZero: true, ticks: { stepSize: 1 }, grid: { color: "rgba(183,201,192,0.35)" } },
                y: { grid: { display: false } },
            },
        },
    });

    // sparkline of recovered vs pending
    upsertChart("spark", "spark-recovered", {
        type: "line",
        data: {
            labels: series.labels.length ? series.labels : ["A", "B", "C", "D", "E"],
            datasets: [
                {
                    data: series.recovered.length
                        ? series.recovered.map((v, i) => v + (series.pending[i] || 0))
                        : [0, 0, 0, 0, 0],
                    borderColor: COLORS.recover,
                    backgroundColor: "rgba(15,138,75,0.12)",
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    borderWidth: 2,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { x: { display: false }, y: { display: false } },
        },
    });

    renderFunnel(s, outcomes);
}

function renderFunnel(summary, outcomes) {
    const el = document.getElementById("funnel-bars");
    if (!el) return;
    const scanned = Number(summary.payments_scanned || 0);
    const issues = Number(summary.issues_found || 0);
    const acted = outcomes.recovered + outcomes.pending;
    const recovered = outcomes.recovered;
    const max = Math.max(scanned, 1);
    const rows = [
        ["Scanned", scanned],
        ["Issues found", issues],
        ["Action taken", acted],
        ["Confirmed recovered", recovered],
    ];
    el.innerHTML = rows
        .map(
            ([label, val]) => `
        <div class="funnel-row">
            <span>${label}</span>
            <div class="funnel-track"><div class="funnel-fill" style="width:${Math.max(6, (val / max) * 100)}%"></div></div>
            <strong>${val}</strong>
        </div>`
        )
        .join("");
}

function renderInsights(data) {
    const empty = document.getElementById("insights-empty");
    const body = document.getElementById("insights-body");
    if (!data) {
        empty?.classList.remove("hidden");
        body?.classList.add("hidden");
        return;
    }
    empty?.classList.add("hidden");
    body?.classList.remove("hidden");
    const s = data.summary || {};
    setText("ins-recovered-num", formatNum(s.amount_recovered_inr));
    setText("ins-recovered", formatINR(s.amount_recovered_inr));
    setText("ins-pending", formatINR(s.amount_pending_inr));
    setText("ins-at-risk", formatINR(s.amount_at_risk_inr));
    setText(
        "ins-summary",
        `${s.issues_found || 0} issues · ${s.escalations || 0} escalations · ${s.payments_scanned || 0} scanned`
    );
}

async function runScan() {
    showView("scan");
    document.getElementById("scan-results")?.classList.add("hidden");
    document.getElementById("loading")?.classList.remove("hidden");
    updateStoryRail(false);
    document.getElementById("story-action")?.classList.add("active");

    ["scan-btn", "scan-btn-main", "home-scan-btn"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = true;
    });

    animateSteps();
    toast("Scan started across 5 engines…");

    try {
        const res = await fetch("/api/scan", { method: "POST" });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        await sleep(250);
        lastScan = data;
        cacheScan(data);
        renderAll(data);
        document.getElementById("loading")?.classList.add("hidden");
        document.getElementById("scan-results")?.classList.remove("hidden");
        toast("Scan complete — " + formatINR(data.summary?.amount_recovered_inr) + " recovered", "ok");
        refreshIcons();
    } catch (err) {
        toast("Scan failed: " + err.message, "err");
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
    const split = moneySplit(s);
    const rate =
        split.atRisk > 0
            ? Math.round(((split.recovered + split.pending) / split.atRisk) * 100)
            : 0;

    animateValue(document.getElementById("home-recovered"), Number(s.amount_recovered_inr || 0), "₹", 900);
    setText("home-at-risk", formatINR(s.amount_at_risk_inr));
    setText("home-pending", formatINR(s.amount_pending_inr));
    setText("home-escalated", s.escalations || 0);
    setText("home-rate", rate + "%");
    setText(
        "home-rate-line",
        rate ? rate + "% of at-risk money recovered or pending" : "Run a scan to measure recovery"
    );
    updateMoneyStory(s);

    setText("stat-scanned", s.payments_scanned || 0);
    setText("stat-issues", s.issues_found || 0);
    setText("stat-recovered", formatINR(s.amount_recovered_inr));
    setText("stat-pending", formatINR(s.amount_pending_inr));
    setText("stat-escalated", s.escalations || 0);
    setText(
        "scan-result-line",
        `${formatINR(s.amount_recovered_inr)} recovered · ${formatINR(s.amount_pending_inr)} pending · ${s.escalations || 0} escalated`
    );

    const badge = document.getElementById("nav-esc-badge");
    if (badge) {
        badge.textContent = s.escalations || 0;
        badge.dataset.count = String(s.escalations || 0);
    }

    renderEngines(data.engines || []);
    renderIssues(data.engines || []);
    renderEscalations(data.engines || []);
    renderInsights(data);
    loadAudit(data.scan_run_id);
    updateAllCharts(data);
    updateStoryRail(true);

    const mode =
        data.razorpay_mode === "simulated" ? "Mode: Simulated (demo)" : "Mode: Live test";
    setText("mode-indicator", mode);
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
        body.innerHTML = `
          <div class="empty-state" id="escalations-empty">
            <i data-lucide="shield-check"></i>
            <h3>Nothing to review</h3>
            <p>Escalations appear when amount or category needs a human.</p>
          </div>`;
        refreshIcons(body);
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
            trail.innerHTML = `
              <div class="empty-state" id="audit-empty">
                <i data-lucide="scroll-text"></i>
                <h3>Audit is empty</h3>
                <p>Every automated action will appear here after a scan.</p>
              </div>`;
            refreshIcons(trail);
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

    const paint = (cfg) => {
        const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
        const engines = [
            ["Capture Guardian", [
                ["Auto-capture max", inr(cfg.capture_guardian?.auto_capture_threshold_inr)],
                ["Min age", (cfg.capture_guardian?.min_authorized_age_hours || 0) + " hours"],
            ]],
            ["Retry Strategist", [
                ["Max retries", cfg.retry_strategist?.max_retries_per_payment ?? 2],
                ["Retry gap", (cfg.retry_strategist?.retry_delay_minutes || 30) + " min"],
                ["Min amount", inr(cfg.retry_strategist?.retry_only_above_inr)],
            ]],
            ["Dispute Defender", [
                ["Auto-contest max", inr(cfg.dispute_defender?.auto_contest_threshold_inr)],
                ["Min winnability", cfg.dispute_defender?.min_winnability_score ?? 0.6],
                ["Never auto", (cfg.dispute_defender?.never_auto_contest_categories || ["fraud"]).join(", ")],
            ]],
            ["Refund Resolver", [
                ["Auto-reissue max", inr(cfg.refund_resolver?.auto_reissue_threshold_inr)],
                ["Min pending age", (cfg.refund_resolver?.min_pending_age_days || 0) + " days"],
            ]],
            ["Checkout Rescuer", [
                ["Min order", inr(cfg.checkout_rescuer?.min_order_amount_inr)],
                ["Wait before send", (cfg.checkout_rescuer?.delay_before_recovery_minutes || 30) + " min"],
                ["Give up after", (cfg.checkout_rescuer?.give_up_after_hours || 24) + " hours"],
                ["Max messages", cfg.checkout_rescuer?.max_recovery_messages_per_order ?? 1],
            ]],
        ];
        body.innerHTML = engines
            .map(
                ([title, rows]) => `
            <div class="rule-card">
                <h4>${title}</h4>
                <ul>${rows.map(([k, v]) => `<li><strong>${k}:</strong> ${v ?? "—"}</li>`).join("")}</ul>
            </div>`
            )
            .join("");
        body.dataset.rulesState = "live";
    };

    // Never wipe existing cards to "Loading…" — only show spinner if empty
    if (!body.querySelector(".rule-card")) {
        body.innerHTML = '<p class="lead">Loading…</p>';
    }

    try {
        const res = await fetch(new URL("/api/boundaries", window.location.origin).toString(), {
            cache: "no-store",
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const cfg = await res.json();
        paint(cfg);
    } catch (err) {
        // Keep static fallback cards if present; otherwise show error
        if (!body.querySelector(".rule-card")) {
            body.innerHTML = `<p class="lead">Could not load rules (${err.message}).</p>`;
        }
        body.dataset.rulesState = "fallback";
        console.warn("loadRules failed, keeping fallback:", err);
    }
}

async function resetDemo() {
    if (!confirm("Clear previous scans and start fresh?")) return;
    await fetch("/api/reset", { method: "POST" });
    lastScan = null;
    localStorage.removeItem(SCAN_CACHE_KEY);
    Object.keys(charts).forEach(destroyChart);

    setText("home-recovered", "₹0");
    setText("home-at-risk", "₹0");
    setText("home-pending", "₹0");
    setText("home-escalated", "0");
    setText("home-rate", "0%");
    setText("home-rate-line", "Run a scan to measure recovery");
    updateMoneyStory({});

    const badge = document.getElementById("nav-esc-badge");
    if (badge) {
        badge.textContent = "0";
        badge.dataset.count = "0";
    }

    document.getElementById("scan-results")?.classList.add("hidden");
    document.getElementById("issues-wrap")?.classList.add("hidden");
    document.getElementById("issues-empty")?.classList.remove("hidden");
    document.getElementById("insights-empty")?.classList.remove("hidden");
    document.getElementById("insights-body")?.classList.add("hidden");
    renderEscalations([]);
    document.getElementById("audit-trail").innerHTML = `
      <div class="empty-state" id="audit-empty">
        <i data-lucide="scroll-text"></i>
        <h3>Audit is empty</h3>
        <p>Every automated action will appear here after a scan.</p>
      </div>`;
    updateStoryRail(false);
    showView("home");
    refreshIcons();
    toast("Demo reset", "ok");
}

async function initAppData() {
    try {
        const h = await fetch("/health").then((r) => r.json());
        const session = getSession();
        let mode = h.razorpay_api === "simulated" ? "Mode: Simulated (demo)" : "Mode: Live test";
        if (session?.demoMode) mode = "Mode: Demo data";
        if (session?.keyId) mode = "Mode: Keys connected";
        setText("mode-indicator", mode);
    } catch {
        setText("mode-indicator", "Mode: offline");
    }

    loadRules();
    // Start at ₹0 — amounts appear only after the user clicks Run scan.
    // Same demo/credentials always produce the same totals after scan (deterministic).
    localStorage.removeItem(SCAN_CACHE_KEY);
    clearOverviewMetrics();
}

function selectRecoveryEta(key) {
    const data = RECOVERY_ETA[key];
    if (!data) return;

    document.querySelectorAll(".eta-tab").forEach((tab) => {
        const on = tab.dataset.eta === key;
        tab.classList.toggle("active", on);
        tab.setAttribute("aria-selected", on ? "true" : "false");
    });

    const detail = document.getElementById("eta-detail");
    if (detail) {
        detail.classList.add("is-switching");
        setTimeout(() => {
            setText("eta-kicker", data.kicker);
            setText("eta-headline", data.headline);
            setText("eta-note", data.note);
            setText("eta-range", data.range);
            setText("eta-speed-label", data.speedLabel);
            setText("eta-window-text", data.window);

            const steps = document.getElementById("eta-steps");
            if (steps) {
                steps.innerHTML = data.steps.map((s) => `<li>${s}</li>`).join("");
            }

            const fill = document.getElementById("eta-speed-fill");
            if (fill) {
                fill.style.width = "0%";
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        fill.style.width = data.speed + "%";
                    });
                });
            }

            detail.classList.remove("is-switching");
            refreshIcons(detail);
        }, 120);
    }
}

async function boot() {
    refreshIcons();
    selectRecoveryEta("capture_guardian");
    // Rules must load regardless of auth / scan state
    loadRules();

    await ensureServerAwake();

    const session = getSession();
    if (session?.razorpayConnected) {
        enterApp(session);
    } else {
        showAuthGate();
        if (session && !session.razorpayConnected) {
            enterConnectFlow("auth-razorpay");
        }
    }
}

// Events
document.getElementById("btn-enter-revivo")?.addEventListener("click", () => enterConnectFlow("auth-razorpay"));
document.getElementById("btn-cine-demo")?.addEventListener("click", () => {
    document.getElementById("cinematic")?.classList.add("hidden");
    connectRazorpay(true);
});
document.getElementById("btn-razorpay-path")?.addEventListener("click", () => showAuthStep("auth-razorpay"));
document.getElementById("btn-signup-path")?.addEventListener("click", () => showAuthStep("auth-signup"));
document.getElementById("btn-auth-more")?.addEventListener("click", () => showAuthStep("auth-signup"));
document.getElementById("back-from-signup")?.addEventListener("click", () => showAuthStep("auth-razorpay"));
document.getElementById("btn-connect-rzp")?.addEventListener("click", () => connectRazorpay(false));
document.getElementById("btn-demo-mode")?.addEventListener("click", () => connectRazorpay(true));
document.getElementById("btn-create-account")?.addEventListener("click", createAccount);
document.getElementById("logout-btn")?.addEventListener("click", () => {
    clearSession();
    showAuthGate();
    toast("Logged out");
});

document.getElementById("sidebar-nav")?.addEventListener("click", (e) => {
    const btn = e.target.closest(".nav-item");
    if (!btn) return;
    showView(btn.dataset.view);
});

document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.goto));
});

document.getElementById("eta-tabs")?.addEventListener("click", (e) => {
    const tab = e.target.closest("[data-eta]");
    if (!tab) return;
    selectRecoveryEta(tab.dataset.eta);
});

document.getElementById("scan-btn")?.addEventListener("click", runScan);
document.getElementById("scan-btn-main")?.addEventListener("click", runScan);
document.getElementById("home-scan-btn")?.addEventListener("click", runScan);
document.getElementById("reset-btn")?.addEventListener("click", resetDemo);

document.getElementById("menu-toggle")?.addEventListener("click", () => {
    document.querySelector(".sidebar")?.classList.add("open");
    document.getElementById("sidebar-backdrop")?.classList.add("show");
});
document.getElementById("sidebar-backdrop")?.addEventListener("click", () => {
    document.querySelector(".sidebar")?.classList.remove("open");
    document.getElementById("sidebar-backdrop")?.classList.remove("show");
});

boot();
