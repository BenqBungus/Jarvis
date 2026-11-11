"""Explicit Google desktop OAuth; no token files, passwords or automatic login."""
from __future__ import annotations

import json
from pathlib import Path

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
TOKEN_URI = "https://oauth2.googleapis.com/token"
TARGET = "Jarvis/Gmail/ReadOnly"


class GmailError(Exception):
    """A user-facing error that must not contain provider response bodies."""


class GmailCredentialStore:
    def __init__(self, target: str = TARGET) -> None:
        # One Credential Manager entry per profile (profiles.py); TARGET is the first profile's.
        self.target = target

    def load(self):
        try:
            import win32cred
            entry = win32cred.CredRead(self.target, win32cred.CRED_TYPE_GENERIC, 0)
            data = entry["CredentialBlob"]
            return json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        except ImportError:
            raise GmailError("Gmail requires pywin32 for Windows Credential Manager.") from None
        except Exception as exc:
            if getattr(exc, "winerror", None) == 1168:
                return None
            raise GmailError("Cannot read Gmail authorization from Windows Credential Manager.") from None

    def save(self, data):
        try:
            import win32cred
            blob = json.dumps(data).encode("utf-8")
            if len(blob) > 2560:
                raise ValueError("credential too large")
            win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC, "TargetName": self.target,
                                "UserName": "Jarvis", "CredentialBlob": blob,
                                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)
        except Exception:
            raise GmailError("Cannot securely save Gmail authorization; no plaintext token was written.") from None

    def remove(self):
        try:
            import win32cred
            win32cred.CredDelete(self.target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            if getattr(exc, "winerror", None) != 1168:
                raise GmailError("Cannot remove Gmail authorization from Windows Credential Manager.") from None


def _validate_credentials(data):
    if not isinstance(data, dict) or data.get("token_uri") != TOKEN_URI:
        raise GmailError("Invalid Gmail authorization. Disconnect and connect again.")
    if set(data.get("scopes") or []) != {SCOPE}:
        raise GmailError("Gmail requires a separate read-only authorization. Connect again.")
    if not all(isinstance(data.get(key), str) and data[key] for key in ("client_id", "client_secret", "refresh_token")):
        raise GmailError("Gmail authorization is incomplete. Connect again.")
    return data


class GmailAuth:
    def __init__(self, store=None):
        self.store = store if store is not None else GmailCredentialStore()

    def connected(self):
        data = self.store.load()
        if data is None:
            return False
        _validate_credentials(data)
        return True

    def connect(self, client_file, *, cancelled=lambda: False):
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            raise GmailError("Install the optional Gmail dependencies in docs/GMAIL_SETUP.md first.") from None
        try:
            path = Path(client_file)
            if not path.is_file() or path.stat().st_size > 65536:
                raise ValueError("invalid client file")
            config = json.loads(path.read_text(encoding="utf-8"))["installed"]
            if not all(isinstance(config.get(key), str) and config[key] for key in ("client_id", "client_secret")):
                raise ValueError("invalid client")
            if not config["client_id"].endswith(".apps.googleusercontent.com"):
                raise ValueError("invalid client id")
        except Exception:
            raise GmailError("Choose Google's downloaded OAuth client JSON for a Desktop app, not an API key.") from None
        if cancelled():
            raise GmailError("Gmail connection cancelled.")
        # Do not trust endpoints supplied by an arbitrary downloaded JSON file.
        trusted_config = {"installed": {"client_id": config["client_id"], "client_secret": config["client_secret"],
                           "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": TOKEN_URI,
                           "redirect_uris": ["http://localhost"]}}
        try:
            flow = InstalledAppFlow.from_client_config(trusted_config, [SCOPE], autogenerate_code_verifier=True)
            credentials = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True,
                timeout_seconds=120, authorization_prompt_message="",
                success_message="Jarvis authorization received. You can close this tab.",
                access_type="offline", prompt="consent select_account", include_granted_scopes="false")
            scopes = credentials.granted_scopes or credentials.scopes
            data = {"client_id": credentials.client_id, "client_secret": credentials.client_secret,
                    "refresh_token": credentials.refresh_token, "token_uri": TOKEN_URI, "scopes": list(scopes or [])}
            _validate_credentials(data)
        except GmailError:
            raise
        except Exception:
            raise GmailError("Google sign-in failed, was declined or timed out. Check the Desktop OAuth client and test-user setup.") from None
        if cancelled():
            raise GmailError("Gmail connection cancelled; authorization was not saved. You can revoke Jarvis in your Google account.")
        self.store.save(data)

    def disconnect(self):
        self.store.remove()

    def client(self):
        data = self.store.load()
        if data is None:
            raise GmailError("Gmail is not connected. Open Settings > Gmail and connect your Google account.")
        _validate_credentials(data)
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_httplib2 import AuthorizedHttp
            from googleapiclient.discovery import build
            import httplib2
        except ImportError:
            raise GmailError("Install the optional Gmail dependencies in docs/GMAIL_SETUP.md first.") from None
        try:
            credentials = Credentials.from_authorized_user_info(data, [SCOPE])
            credentials.refresh(Request())
            return build("gmail", "v1", http=AuthorizedHttp(credentials, http=httplib2.Http(timeout=20)),
                         cache_discovery=False, static_discovery=True)
        except Exception:
            raise GmailError("Gmail authorization could not be refreshed. Check your connection or reconnect Gmail.") from None
