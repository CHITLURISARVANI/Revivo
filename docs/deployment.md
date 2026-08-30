# Deployment — Revivo: AI Revenue Recovery Agent

> Infrastructure, CI/CD, observability, and secrets management.
> Informed by all preceding spec documents.

---

## 1. Infrastructure Overview

```
┌─────────────────────────────────────────────┐
│              Developer Machine               │
│                                             │
│  ┌─────────────┐    ┌──────────────────┐    │
│  │  Docker      │    │  Revivo Container│   │
│  │  Engine      │───▶│  (uvicorn + app)  │   │
│  └─────────────┘    └────────┬─────────┘    │
│                              │              │
└──────────────────────────────┼──────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
            ┌───────▼───────┐    ┌────────▼────────┐
            │  Razorpay API  │    │  OpenAI API     │
            │  (Test Mode)   │    │  (optional)     │
            └────────────────┘    └─────────────────┘
```

v1 is a **single-container deployment**. No load balancer, no reverse proxy, no database. Suitable for hackathon demo and local development. The architecture supports scaling up (add Redis for sessions, add workers, add Nginx) but that's out of scope for v1.

---

## 2. Dockerfile (Multi-Stage)

```dockerfile
# ── Stage 1: Builder ──
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Production ──
FROM python:3.11-slim AS production

# Non-root user for security
RUN useradd -m -s /bin/bash Revivo
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=Revivo:Revivo src/ ./src/
COPY --chown=Revivo:Revivo demo.py .
COPY --chown=Revivo:Revivo README.md .

# Switch to non-root user
USER Revivo

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

# Run with uvicorn
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### Docker Build & Run

```bash
# Build
docker build -t Revivo:latest .

# Run (no OpenAI key — uses static fallback)
docker run -p 8000:8000 Revivo:latest

# Run with OpenAI key (enables AI diagnosis)
docker run -p 8000:8000 -e OPENAI_API_KEY=sk-... Revivo:latest

# Run for development (with reload)
docker run -p 8000:8000 -v $(pwd)/src:/app/src Revivo:latest \
    uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
```

---

## 3. Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | No | None | OpenAI API key for LLM diagnosis. If absent, static fallback rules are used. |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Model to use for classification/evidence drafting. |
| `MAX_INTERVENTIONS` | No | `50` | Max interventions per batch (safety cap). |
| `RATE_LIMIT_PER_SEC` | No | `8` | Max Razorpay API calls per second. |
| `SESSION_TTL_SECONDS` | No | `3600` | Session store entry TTL. |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR). |

### .env.example

```bash
# Revivo — Environment Variables
# Copy to .env and fill in your values

# OpenAI (optional — system works without it using static fallback rules)
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

# Safety limits
MAX_INTERVENTIONS=50
RATE_LIMIT_PER_SEC=8
SESSION_TTL_SECONDS=3600

# Logging
LOG_LEVEL=INFO
```

---

## 4. CI/CD Pipeline

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    name: Lint (ruff)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install ruff
      - run: ruff check src/ tests/

  typecheck:
    name: Type Check (mypy)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install mypy
      - run: mypy src/ --ignore-missing-imports

  test:
    name: Tests + Coverage
    runs-on: ubuntu-latest
    needs: [lint, typecheck]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pip install pytest pytest-cov pytest-asyncio
      - run: pytest --cov=src --cov-report=term-missing --cov-fail-under=85 -v

  validate-openapi:
    name: Validate OpenAPI Spec
    runs-on: ubuntu-latest
    needs: [lint]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install pyyaml
      - run: python scripts/validate-openapi.py docs/api-spec.yaml

  docker-build:
    name: Docker Build
    runs-on: ubuntu-latest
    needs: [test, validate-openapi]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - run: docker build -t Revivo:latest .
      - run: docker run -d -p 8000:8000 --name Revivo-test Revivo:latest
      - run: sleep 3 && curl -sf http://localhost:8000/health
      - run: docker stop Revivo-test && docker rm Revivo-test
```

### Pipeline Stages (8 stages)

1. **Lint** — ruff check on src/ and tests/
2. **Type check** — mypy on src/
3. **Tests + Coverage** — pytest with ≥85% coverage gate
4. **OpenAPI validation** — structural validation of api-spec.yaml
5. **Docker build** — multi-stage build
6. **Container smoke test** — health check on running container
7. *(future)* **Deploy to staging** — push to registry
8. *(future)* **Deploy to production** — blue-green with rollback

---

## 5. Observability

### 5.1 Structured Logging

Using `logging` with JSON formatter:

```python
import logging, json, sys

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "batch_id": getattr(record, "batch_id", None),
        }
        return json.dumps(log)

logger = logging.getLogger("Revivo")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
```

**Redaction**: The `RazorpayClient` and `AuditLog` redact sensitive fields before logging:
- `key_id` → `key_***XXXX` (last 4 chars)
- `key_secret` → `***REDACTED***`
- `card_number` → `****-****-****-XXXX`
- `cvv` → `***`

### 5.2 Health Endpoint

```python
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - START_TIME),
    }
```

Returns `200` when healthy, `503` when unhealthy (e.g., if startup fails).

### 5.3 Metrics (Future-Ready)

v1 includes a `/metrics` endpoint stub that returns basic Prometheus-format metrics:

```
# HELP Revivo_scans_total Total scans triggered
# TYPE Revivo_scans_total counter
Revivo_scans_total 42

# HELP Revivo_leaks_detected_total Total leaks detected by type
# TYPE Revivo_leaks_detected_total counter
Revivo_leaks_detected_total{type="L1"} 15
Revivo_leaks_detected_total{type="L2"} 8

# HELP Revivo_interventions_total Total interventions by status
# TYPE Revivo_interventions_total counter
Revivo_interventions_total{status="executed"} 12
Revivo_interventions_total{status="failed"} 2
Revivo_interventions_total{status="skipped_dry_run"} 30

# HELP Revivo_razorpay_api_duration_ms Razorpay API call duration
# TYPE Revivo_razorpay_api_duration_ms histogram
Revivo_razorpay_api_duration_ms_bucket{le="100"} 45
Revivo_razorpay_api_duration_ms_bucket{le="500"} 52
```

### 5.4 Audit Trail as Observability

The `AuditLog` is the primary observability mechanism for money actions. Every Razorpay API call is recorded with:
- Timestamp (ISO 8601)
- Endpoint + method
- Request body (redacted)
- Response status + body (redacted)
- Duration in ms
- Success/failure

This is embedded in the `RecoveryReport` returned to the user — the audit trail IS the product feature, not just internal observability.

---

## 6. Secrets Management

| Secret | Where Stored | How Accessed |
|--------|-------------|--------------|
| Razorpay Key ID | Per-request HTTP header (`X-Razorpay-Key-Id`) | Held in memory for scan duration only. Never persisted, never logged. |
| Razorpay Key Secret | Per-request HTTP header (`X-Razorpay-Key-Secret`) | Same as above. Redacted in all logs and audit entries. |
| OpenAI API Key | `.env` file or `OPENAI_API_KEY` env var | Read once at startup. If absent, system uses static fallback (no AI). |
| Docker image secrets | Docker build args or env vars at `docker run` | Never baked into image layers. |

**Rules:**
1. No secrets in source code (enforced by ruff custom rule + git pre-commit hook scanning for `key_`, `secret`, `sk-`)
2. No secrets in Docker image (only env vars passed at runtime)
3. No secrets in logs (redaction in `JsonFormatter` + `AuditLog`)
4. No secrets in API responses (Pydantic `exclude` on sensitive fields)
5. `.env` in `.gitignore` (enforced)
6. `.env.example` contains only empty values (safe to commit)

---

## 7. Local Development Setup

```bash
# Clone
git clone https://github.com/sahil/Revivo.git
cd Revivo

# Create venv
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or: .venv\Scripts\activate  # Windows

# Install deps
pip install -r requirements.txt
pip install -e .  # If pyproject.toml exists, or just run from src/

# Optional: Set OpenAI key for AI diagnosis
cp .env.example .env
# Edit .env: add OPENAI_API_KEY=sk-...

# Run tests
python -m pytest --cov=src --cov-report=term-missing -v

# Run server
uvicorn src.server:app --reload --port 8000

# Run demo
python demo.py

# Docker (optional)
docker build -t Revivo:latest .
docker run -p 8000:8000 Revivo:latest
```

### Requirements

```txt
# requirements.txt
fastapi==0.115.0
uvicorn==0.30.0
httpx==0.27.0
openai==1.40.0
pydantic==2.7.0
python-dotenv==1.0.0

# Dev dependencies (install separately for development)
# pytest==8.3.0
# pytest-cov==5.0.0
# pytest-asyncio==0.23.0
# ruff==0.5.0
# mypy==1.11.0
```

---

## 8. Deployment Checklist (Pre-Submission)

- [ ] All tests pass (`pytest --cov-fail-under=85`)
- [ ] Lint passes (`ruff check src/ tests/`)
- [ ] OpenAPI spec validates (`python scripts/validate-openapi.py`)
- [ ] Docker build succeeds
- [ ] Container health check passes
- [ ] Demo script runs end-to-end (`python demo.py`)
- [ ] README has quickstart + architecture overview
- [ ] No secrets in git history (`git log --all -p | grep -i "key_secret"`)
- [ ] `.env` is in `.gitignore`
- [ ] Repo is pushed to GitHub
- [ ] 5-minute pitch video recorded
