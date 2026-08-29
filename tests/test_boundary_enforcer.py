"""Boundary enforcer tests."""

from core.boundary_enforcer import check_action


def test_capture_below_threshold_allowed(boundaries_config):
    result = check_action("capture_guardian", "auto_capture", 12000)
    assert result.allowed is True
    assert result.reason == "within_bounds"


def test_capture_above_threshold_blocked_and_escalated(boundaries_config):
    result = check_action("capture_guardian", "auto_capture", 65000)
    assert result.allowed is False
    assert result.reason == "amount_exceeds_threshold"
    assert result.escalate is True


def test_fraud_dispute_always_escalated(boundaries_config):
    result = check_action("dispute_defender", "auto_contest", 5000, category="fraud")
    assert result.allowed is False
    assert "category_restricted" in result.reason
    assert result.escalate is True


def test_max_retries_exceeded_blocked(boundaries_config):
    result = check_action("retry_strategist", "retry", 4500, retry_count=2)
    assert result.allowed is False
    assert result.reason == "max_retries_exceeded"


def test_disabled_engine_blocked(boundaries_config, monkeypatch, tmp_path):
    import json
    from core import boundary_enforcer

    config = boundaries_config.copy()
    config["capture_guardian"] = {**config["capture_guardian"], "enabled": False}
    path = tmp_path / "boundaries_disabled.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(boundary_enforcer, "BOUNDARIES_PATH", str(path))

    result = check_action("capture_guardian", "auto_capture", 1000)
    assert result.allowed is False
    assert result.reason == "engine_disabled"
