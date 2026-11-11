import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from jarvis.gmail_auth import GmailAuth, GmailCredentialStore, GmailError, SCOPE, TOKEN_URI, TARGET


def credential():
    return {"client_id": "test.apps.googleusercontent.com", "client_secret": "fake-client",
            "refresh_token": "fake-refresh", "token_uri": TOKEN_URI, "scopes": [SCOPE]}


@pytest.fixture
def oauth(tmp_path, monkeypatch):
    flow_module = ModuleType("google_auth_oauthlib.flow")
    factory = Mock()
    creds = SimpleNamespace(**credential(), granted_scopes=[SCOPE])
    factory.from_client_config.return_value.run_local_server.return_value = creds
    flow_module.InstalledAppFlow = factory
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", ModuleType("google_auth_oauthlib"))
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_module)
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"installed": {"client_id": creds.client_id, "client_secret": creds.client_secret,
                                             "auth_uri": "https://evil.invalid", "token_uri": "https://evil.invalid"}}))
    store = Mock(load=Mock(return_value=None))
    return SimpleNamespace(auth=GmailAuth(store), store=store, factory=factory, path=path, creds=creds)


def test_oauth_uses_fixed_google_endpoints_loopback_and_pkce(oauth):
    oauth.auth.connect(oauth.path)
    args, kwargs = oauth.factory.from_client_config.call_args
    assert args[0]["installed"]["token_uri"] == TOKEN_URI
    assert args[0]["installed"]["auth_uri"].startswith("https://accounts.google.com/")
    assert args[1] == [SCOPE] and kwargs["autogenerate_code_verifier"]
    call = oauth.factory.from_client_config.return_value.run_local_server.call_args.kwargs
    assert call["host"] == "127.0.0.1" and call["port"] == 0
    assert call["timeout_seconds"] == 120
    assert call["authorization_prompt_message"] == ""
    oauth.store.save.assert_called_once_with(credential())


def test_cancel_after_browser_never_persists_authorization(oauth):
    cancelled = Mock(side_effect=[False, True])
    with pytest.raises(GmailError, match="not saved"):
        oauth.auth.connect(oauth.path, cancelled=cancelled)
    oauth.store.save.assert_not_called()


def test_broader_scopes_are_rejected(oauth):
    oauth.creds.granted_scopes = [SCOPE, "https://mail.google.com/"]
    with pytest.raises(GmailError, match="read-only"):
        oauth.auth.connect(oauth.path)
    oauth.store.save.assert_not_called()


def test_invalid_client_and_provider_errors_do_not_leak(oauth):
    oauth.factory.from_client_config.return_value.run_local_server.side_effect = RuntimeError("secret token")
    with pytest.raises(GmailError) as error:
        oauth.auth.connect(oauth.path)
    assert "secret token" not in str(error.value)
    oauth.path.write_text('{"web":{}}')
    with pytest.raises(GmailError, match="Desktop"):
        oauth.auth.connect(oauth.path)


def test_status_never_refreshes_or_starts_oauth():
    store = Mock(load=Mock(return_value=credential()))
    assert GmailAuth(store).connected()
    store.save.assert_not_called()
    store.load.return_value = None
    assert not GmailAuth(store).connected()


def test_client_rejects_untrusted_token_endpoint_before_network():
    data = credential()
    data["token_uri"] = "https://evil.invalid"
    with pytest.raises(GmailError):
        GmailAuth(Mock(load=Mock(return_value=data))).client()


def test_credential_manager_roundtrip_is_separate_from_openai(monkeypatch):
    win32 = ModuleType("win32cred")
    win32.CRED_TYPE_GENERIC = 1
    win32.CRED_PERSIST_LOCAL_MACHINE = 2
    win32.CredWrite = Mock()
    win32.CredRead = Mock()
    win32.CredDelete = Mock()
    monkeypatch.setitem(sys.modules, "win32cred", win32)
    store = GmailCredentialStore()
    store.save(credential())
    entry = win32.CredWrite.call_args.args[0]
    assert entry["TargetName"] == TARGET
    assert "OpenAI" not in TARGET
    win32.CredRead.return_value = {"CredentialBlob": entry["CredentialBlob"]}
    assert store.load() == credential()
    store.remove()
    win32.CredDelete.assert_called_once_with(TARGET, 1, 0)


def test_credential_storage_failure_has_no_plaintext_fallback(monkeypatch, tmp_path):
    win32 = ModuleType("win32cred")
    monkeypatch.setitem(sys.modules, "win32cred", win32)
    with pytest.raises(GmailError, match="no plaintext"):
        GmailCredentialStore().save(credential())
    assert list(tmp_path.iterdir()) == []
