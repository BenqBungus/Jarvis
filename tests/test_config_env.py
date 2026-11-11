from __future__ import annotations

import os
import types

from jarvis import config


def test_ensure_openai_api_key_visible_uses_existing_process_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")

    assert config.ensure_openai_api_key_visible() is True


def test_ensure_openai_api_key_visible_loads_user_key_on_windows(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("JARVIS_LOAD_USER_OPENAI_API_KEY", "1")
    monkeypatch.setattr(config.os, "name", "nt")

    class _FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    fake_winreg = types.SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        OpenKey=lambda _root, _path: _FakeKey(),
        QueryValueEx=lambda _key, _name: ("user-key", 1),
    )
    monkeypatch.setitem(__import__("sys").modules, "winreg", fake_winreg)

    try:
        assert config.ensure_openai_api_key_visible() is True
        assert config.os.getenv("OPENAI_API_KEY") == "user-key"
    finally:
        os.environ.pop("OPENAI_API_KEY", None)


def test_ensure_openai_api_key_visible_returns_false_when_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("JARVIS_LOAD_USER_OPENAI_API_KEY", "1")
    monkeypatch.setattr(config.os, "name", "posix")

    assert config.ensure_openai_api_key_visible() is False


def test_ensure_openai_api_key_visible_can_skip_user_registry(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("JARVIS_LOAD_USER_OPENAI_API_KEY", "0")
    monkeypatch.setattr(config.os, "name", "nt")

    assert config.ensure_openai_api_key_visible() is False
