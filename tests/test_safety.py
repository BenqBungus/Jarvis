from __future__ import annotations

import builtins

from jarvis.safety import SafetyPolicy


def test_confirmation_without_stdin_cancels_cleanly(monkeypatch):
    def raise_eof(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr(builtins, "input", raise_eof)

    assert SafetyPolicy(auto_confirm=False).confirm("Test action", "Needs approval.") is False
