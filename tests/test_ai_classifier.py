"""AI classifier + fallback tests."""

from ai.classifier import classify_failure
from ai.fallback import classify_failure_fallback


def test_classify_upi_s2s_declined_as_transient():
    result = classify_failure({
        "error_code": "UPI_S2S_DECLINED",
        "error_description": "UPI transaction declined by remitter bank",
        "method": "upi",
        "amount": 4500,
    })
    assert result["classification"] == "transient"
    assert result["retry_recommended"] is True
    assert "classification" in result
    assert "confidence" in result
    assert "reasoning" in result


def test_classify_insufficient_funds_as_permanent():
    result = classify_failure({
        "error_code": "INSUFFICIENT_FUNDS",
        "error_description": "Insufficient funds",
        "method": "upi",
        "amount": 2200,
    })
    assert result["classification"] == "permanent"
    assert result["retry_recommended"] is False


def test_fallback_when_api_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = classify_failure_fallback({
        "error_code": "NETWORK_TIMEOUT",
        "error_description": "Network timeout",
    })
    assert result["classification"] == "transient"


def test_output_is_valid_json_structure():
    result = classify_failure({"error_code": "UNKNOWN_XYZ"})
    assert isinstance(result, dict)
    assert result["classification"] in ("transient", "permanent", "ambiguous")
    assert 0 <= result["confidence"] <= 1
    assert isinstance(result["reasoning"], str)
