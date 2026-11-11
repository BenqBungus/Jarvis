from __future__ import annotations

from jarvis.privacy import contains_sensitive_text, redact_sensitive_data, redact_sensitive_text


def test_redact_sensitive_text_handles_openai_project_keys():
    result = redact_sensitive_text("my key is sk-proj-abcdefghijklmnopqrstuvwxyz123456")

    assert result.redacted is True
    assert result.findings == ("openai_api_key",)
    assert "sk-proj-" not in result.text
    assert "[REDACTED_SECRET]" in result.text


def test_redact_sensitive_text_handles_password_assignments():
    result = redact_sensitive_text("password: hunter2")

    assert result.redacted is True
    assert result.text == "password: [REDACTED_SECRET]"
    assert contains_sensitive_text("парола=secret123") is True


def test_redact_sensitive_data_recurses_through_metadata():
    data = {
        "args": {"token": "Bearer abcdefghijklmnopqrstuvwxyz"},
        "items": ["api_key: abcdefghijk12345"],
        "ok": True,
    }

    redacted = redact_sensitive_data(data)

    assert redacted["args"]["token"] == "Bearer [REDACTED_SECRET]"
    assert redacted["items"] == ["api_key: [REDACTED_SECRET]"]
    assert redacted["ok"] is True
