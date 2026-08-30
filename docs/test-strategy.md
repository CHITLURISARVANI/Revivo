# Test Strategy — Revivo: AI Revenue Recovery Agent

> Testing pyramid, coverage targets, and specific test cases.
> Informed by [api-spec.yaml](./api-spec.yaml), [data-model.md](./data-model.md), and [architecture.md](./architecture.md).

---

## 1. Testing Pyramid

```
        ┌───────┐
        │  E2E  │  5%  — Full scan lifecycle with mocked Razorpay API
        ├───────┤
        │  Int  │  20% — FastAPI TestClient + mocked external APIs
        ├───────┤
        │  Unit │  75% — Pure logic: scanner filters, diagnosis rules, stopping rules, report calc
        └───────┘
```

## 2. Coverage Targets

| Layer | Target | Measurement |
|-------|--------|-------------|
| `scanner.py` | ≥ 90% | `pytest-cov` line coverage |
| `diagnostician.py` | ≥ 85% | `pytest-cov` line coverage |
| `intervenor.py` | ≥ 90% | `pytest-cov` line coverage (stopping rules are critical) |
| `reporter.py` | ≥ 85% | `pytest-cov` line coverage |
| `razorpay_client.py` | ≥ 80% | `pytest-cov` (httpx mock) |
| `llm_client.py` | ≥ 75% | `pytest-cov` (OpenAI mock) |
| `session.py` | ≥ 90% | `pytest-cov` |
| `server.py` | ≥ 80% | Integration via TestClient |
| **Overall** | **≥ 85%** | Combined |

## 3. Test File Structure

```
tests/
├── conftest.py                # Shared fixtures: mock Razorpay responses, mock LLM, test data
├── test_scanner.py            # Unit: filter logic, pagination, leak detection per type
├── test_diagnostician.py      # Unit: L1-L5 diagnosis rules, AI fallback, confidence
├── test_intervenor.py         # Unit: stopping rules, dry_run mode, bounded actions
├── test_stopping_rules.py     # Dedicated: all stopping rule combinations
├── test_reporter.py           # Unit: report calculation, format output, audit trail
├── test_razorpay_client.py    # Unit: API wrapper, pagination, error handling, rate limiting
├── test_llm_client.py         # Unit: LLM calls, fallback, timeout, retry
├── test_session.py            # Unit: store, TTL expiry, thread safety
└── test_server.py             # Integration: FastAPI TestClient, all 3 endpoints
```

## 4. Fixtures (conftest.py)

### Mock Razorpay API Responses

```python
@pytest.fixture
def mock_authorized_payment():
    """Razorpay payment in 'authorized' status, created 2 hours ago."""
    return {
        "id": "pay_test_auth_001",
        "status": "authorized",
        "amount": 500000,          # ₹5000 in paise
        "currency": "INR",
        "created_at": int(time.time()) - 7200,  # 2 hours ago
        "method": "card",
    }

@pytest.fixture
def mock_failed_payment_retryable():
    """Failed payment with GATEWAY_ERROR (retryable)."""
    return {
        "id": "pay_test_fail_001",
        "status": "failed",
        "amount": 300000,
        "currency": "INR",
        "created_at": int(time.time()) - 3600,
        "error_code": "GATEWAY_ERROR",
        "error_description": "The gateway timed out while processing the payment.",
        "method": "card",
    }

@pytest.fixture
def mock_failed_payment_permanent():
    """Failed payment with CARD_DECLINED (permanent)."""
    return {
        "id": "pay_test_fail_002",
        "status": "failed",
        "amount": 150000,
        "currency": "INR",
        "created_at": int(time.time()) - 3600,
        "error_code": "CARD_DECLINED",
        "error_description": "Card was declined by the issuing bank.",
        "method": "card",
    }

@pytest.fixture
def mock_open_dispute():
    return {
        "id": "disp_test_001",
        "status": "open",
        "amount": 500000,
        "currency": "INR",
        "created_at": int(time.time()) - 86400 * 3,  # 3 days ago
        "dispute_reason": "Service not provided",
        "payment_id": "pay_test_auth_001",
    }

@pytest.fixture
def mock_pending_refund():
    return {
        "id": "rfd_test_001",
        "status": "pending",
        "amount": 200000,
        "currency": "INR",
        "created_at": int(time.time()) - 86400 * 3,  # 72 hours ago
        "payment_id": "pay_test_auth_001",
    }

@pytest.fixture
def mock_abandoned_order():
    return {
        "id": "order_test_001",
        "status": "attempted",
        "amount": 250000,
        "currency": "INR",
        "created_at": int(time.time()) - 7200,  # 2 hours ago
        "attempts": 1,
    }
```

### Mock LLM Responses

```python
@pytest.fixture
def mock_llm_classifier():
    """Mock OpenAI client that returns retryable/permanent classification."""
    class MockLLM:
        def classify_error(self, error_code, error_description):
            return {
                "classification": "retryable" if error_code == "GATEWAY_ERROR" else "permanent",
                "reasoning": f"Error {error_code} classified based on description.",
                "confidence": 0.92,
            }
        def draft_dispute_evidence(self, dispute_reason, transaction_details):
            return {
                "evidence_summary": "Service was delivered as evidenced by...",
                "key_points": ["Digital delivery confirmed", "Customer accessed product"],
                "suggested_documents": ["Delivery confirmation", "Server logs"],
            }
        def generate_recovery_message(self, order_details):
            return {"message": "Complete your purchase and get instant access!"}
    return MockLLM()
```

## 5. Specific Test Cases

### 5.1 Scanner Tests (test_scanner.py)

| Test ID | Description | Input | Expected |
|---------|-------------|-------|----------|
| SC-01 | L1 detection: authorized payment > 1hr | `mock_authorized_payment` (2hrs old) | Leak(L1, recoverable candidate) |
| SC-02 | L1 non-detection: authorized payment < 1hr | Payment 30min old | No leak generated |
| SC-03 | L2 detection: failed payment | `mock_failed_payment_retryable` | Leak(L2) |
| SC-04 | L3 detection: open dispute | `mock_open_dispute` | Leak(L3) |
| SC-05 | L4 detection: pending refund > 48hrs | `mock_pending_refund` (72hrs old) | Leak(L4) |
| SC-06 | L4 non-detection: pending refund < 48hrs | Refund 24hrs old | No leak generated |
| SC-07 | L5 detection: attempted order | `mock_abandoned_order` | Leak(L5) |
| SC-08 | Pagination: 250 payments, page size 100 | 3 pages of mock payments | All 250 fetched, 3 API calls |
| SC-09 | Fetcher failure doesn't abort batch | Disputes API returns 500 | Other leaks still returned, error logged in `fetcher_errors` |
| SC-10 | Amount conversion: paise to rupees | Payment amount=500000 | `Leak.amount_inr == 5000.0` |

### 5.2 Diagnostician Tests (test_diagnostician.py)

| Test ID | Description | Input | Expected |
|---------|-------------|-------|----------|
| DG-01 | L1 within capture window | Leak(L1, age=2hrs) | `recoverable=True`, `action=capture` |
| DG-02 | L1 past capture window | Leak(L1, age=6 days) | `recoverable=False`, reason="capture window expired" |
| DG-03 | L2 LLM classifies retryable | Leak(L2, GATEWAY_ERROR) + mock_llm | `recoverable=True`, `ai_reasoning` not null, `fallback_used=False` |
| DG-04 | L2 LLM classifies permanent | Leak(L2, CARD_DECLINED) + mock_llm | `recoverable=False`, `ai_reasoning` not null |
| DG-05 | L2 fallback when LLM unavailable | Leak(L2, GATEWAY_ERROR), no API key | `recoverable=True`, `fallback_used=True`, `ai_reasoning=None` |
| DG-06 | L2 fallback for unknown error code | Leak(L2, "UNKNOWN_CODE"), no API key | `recoverable=False` (conservative default), `fallback_used=True` |
| DG-07 | L3 within contest window | Leak(L3, age=3 days) | `recoverable=True`, `action=contest` |
| DG-08 | L3 urgent (7-30 days) | Leak(L3, age=10 days) | `recoverable=True`, flagged urgent |
| DG-09 | L3 past contest window | Leak(L3, age=35 days) | `recoverable=False`, reason="past contest deadline" |
| DG-10 | L4 always unrecoverable | Leak(L4) | `recoverable=False`, `action=escalate` |
| DG-11 | L5 within 24hrs | Leak(L5, age=2hrs) | `recoverable=True`, `action=send_link` |
| DG-12 | L5 past 72hrs | Leak(L5, age=80hrs) | `recoverable=False`, reason="too late" |
| DG-13 | AI confidence is between 0 and 1 | Any LLM-classified leak | `0 ≤ ai_confidence ≤ 1` |

### 5.3 Stopping Rules Tests (test_stopping_rules.py)

| Test ID | Description | Setup | Expected |
|---------|-------------|-------|----------|
| SR-01 | Max interventions hit | 50 successful interventions, 51st leak | 51st skipped, `status=skipped_halted`, `halted_reason=max_interventions` |
| SR-02 | 3 consecutive failures halt | 3 consecutive API failures | Batch halts, `status=halted`, `halted_reason=consecutive_failures` |
| SR-03 | 401 immediate halt | Razorpay returns 401 | Batch halts immediately, `halted_reason=auth_failure` |
| SR-04 | Non-consecutive failures don't halt | fail, success, fail, success | Batch continues (counter resets on success) |
| SR-05 | Dry run skips all interventions | `dry_run=True`, 10 recoverable leaks | All `status=skipped_dry_run`, 0 API writes |
| SR-06 | Unrecoverable leaks not intervened | 5 recoverable + 3 unrecoverable | Only 5 intervention attempts, 3 `skipped_unrecoverable` |
| SR-07 | Single attempt per leak | 1 leak, intervention fails | No retry on same leak, `status=failed` |

### 5.4 Reporter Tests (test_reporter.py)

| Test ID | Description | Input | Expected |
|---------|-------------|-------|----------|
| RP-01 | Summary calculation | 3 leaks: ₹5000, ₹3000, ₹2000 at risk. ₹5000 recovered. | `total_at_risk=10000`, `total_recovered=5000`, `recovery_rate=0.5` |
| RP-02 | Per-type breakdown | 2×L1, 1×L2, 1×L3 | 3 LeakTypeSummary entries with correct counts |
| RP-03 | Audit trail included | 5 API calls made | `audit_trail` has 5 entries, each with timestamp + endpoint |
| RP-04 | Text format output | Completed report | String contains "RECOVERY REPORT", "Total at risk", "Total recovered" |
| RP-05 | JSON format output | Completed report | Valid JSON with all required fields |
| RP-06 | Halted report | `status=halted`, `halted_reason=consecutive_failures` | Report includes `halted_reason` field |
| RP-07 | Zero leaks | Empty LeakBatch | `total_leaks=0`, `total_at_risk=0`, `recovery_rate=0` |

### 5.5 Razorpay Client Tests (test_razorpay_client.py)

| Test ID | Description | Mock | Expected |
|---------|-------------|------|----------|
| RC-01 | Fetch payments with status filter | httpx mock: 200 with payment list | List of payment dicts |
| RC-02 | Pagination: multiple pages | httpx mock: 200 page1 (100 items) + 200 page2 (50 items) | 150 total items, 2 API calls |
| RC-03 | API error: 500 | httpx mock: 500 | Raises `RazorpayAPIError` with status 500 |
| RC-04 | API error: 401 | httpx mock: 401 | Raises `RazorpayAPIError` with status 401 |
| RC-05 | Capture payment | httpx mock: 200 captured | Returns capture confirmation dict |
| RC-06 | Create payment link | httpx mock: 200 created | Returns payment link dict |
| RC-07 | Contest dispute | httpx mock: 200 contested | Returns contest confirmation dict |
| RC-08 | Rate limiting: 8 req/sec | 10 rapid calls | Only 8 execute in first second, 2 wait |
| RC-09 | Request redaction in audit | Any API call | `request_body_redacted` does not contain key_secret |
| RC-10 | Timeout handling | httpx mock: timeout | Raises `RazorpayAPIError`, logged in audit |

### 5.6 LLM Client Tests (test_llm_client.py)

| Test ID | Description | Mock | Expected |
|---------|-------------|------|----------|
| LC-01 | Classify error: retryable | OpenAI mock: returns retryable | classification="retryable", confidence=float |
| LC-02 | Classify error: permanent | OpenAI mock: returns permanent | classification="permanent" |
| LC-03 | Fallback on no API key | No env var set | Returns static rule table result, `fallback_used=True` |
| LC-04 | Fallback on timeout | OpenAI mock: timeout | Returns static rule table result, `fallback_used=True` |
| LC-05 | Fallback on rate limit | OpenAI mock: 429 | Returns static rule table result, `fallback_used=True` |
| LC-06 | Dispute evidence drafting | OpenAI mock: returns evidence JSON | Dict with evidence_summary, key_points |
| LC-07 | Recovery message generation | OpenAI mock: returns message | String ≤ 100 chars |

### 5.7 Session Store Tests (test_session.py)

| Test ID | Description | Expected |
|---------|-------------|----------|
| SS-01 | Create and retrieve session | Store → get returns same data |
| SS-02 | TTL expiry | Entry > 1hr old → get returns None, entry deleted |
| SS-03 | Non-existent batch_id | get returns None |
| SS-04 | Thread safety: concurrent access | No race condition, no corruption |

### 5.8 Server Integration Tests (test_server.py)

| Test ID | Description | Setup | Expected |
|---------|-------------|-------|----------|
| SV-01 | POST /scan sync dry_run | Mock Razorpay + mock LLM, dry_run=true | 200, response has batch_id, report, status=completed |
| SV-02 | POST /scan sync execute | Mock Razorpay + mock LLM, dry_run=false | 200, report shows interventions executed |
| SV-03 | POST /scan missing auth | No X-Razorpay-Key-Id header | 401, error.code=AUTH_FAILED |
| SV-04 | POST /scan invalid auth | Bad credentials, Razorpay returns 401 | 401, error.code=AUTH_FAILED |
| SV-05 | GET /report/{id} | Completed batch | 200, full RecoveryReport |
| SV-06 | GET /report/{id} text format | format=text | 200, text/plain, human-readable report |
| SV-07 | GET /report/{id} not found | Random UUID | 404, error.code=BATCH_NOT_FOUND |
| SV-08 | GET /report/{id}/leaks with filter | leak_type=L1 | 200, only L1 leaks in response |
| SV-09 | GET /report/{id}/leaks pagination | limit=2, 5 total leaks | 2 leaks + next_cursor; fetch next page → 2 more |
| SV-10 | GET /health | None | 200, status=healthy |
| SV-11 | Idempotency: same key, same response | POST /scan twice with same Idempotency-Key | Second call returns same batch_id, no re-scan |
| SV-12 | Rate limit: 11th request in a minute | 10 requests, then 11th | 429, error.code=RATE_LIMITED |

## 6. CI Enforcement Rules

```yaml
# .github/workflows/ci.yml (conceptual)
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install deps
        run: pip install -r requirements.txt && pip install pytest pytest-cov pytest-asyncio
      - name: Lint
        run: ruff check src/ tests/
      - name: Type check
        run: mypy src/ --ignore-missing-imports
      - name: Run tests with coverage
        run: pytest --cov=src --cov-report=term-missing --cov-fail-under=85
      - name: Validate OpenAPI spec
        run: python scripts/validate-openapi.py docs/api-spec.yaml
```

**CI fails if:**
- Any test fails
- Coverage < 85%
- Linting errors
- OpenAPI spec invalid
- Type errors

## 7. Test Execution Commands

```bash
# Run all tests with coverage
python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=85 -v

# Run specific module tests
python -m pytest tests/test_stopping_rules.py -v

# Run only integration tests
python -m pytest tests/test_server.py -v

# Run with verbose output and show prints
python -m pytest -v -s

# Generate HTML coverage report
python -m pytest --cov=src --cov-report=html
```
