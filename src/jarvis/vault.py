"""Password vault: the person's passwords, kept by Windows Credential Manager.

Built by Claude on the user's request of 2026-09-28. One vault per profile,
for adult profiles only (permission_levels.py). A password never goes back to
OpenAI, the audit log or memory: tools return names only and carry
private_content, and "tell me the password" shows it in a local window or
spells it with the local Windows voice (gui/vault_ui.py).
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

TARGET_PREFIX = "Jarvis/Vault/"
MAX_NAME = 60
MAX_SECRET = 512


class VaultError(ValueError):
    """A vault problem whose message is safe to show (never contains a secret)."""


@dataclass(frozen=True)
class VaultEntry:
    name: str
    username: str = ""
    updated: str = ""


class CredentialBackend(Protocol):
    def list(self, prefix: str) -> list[dict]: ...
    def read(self, target: str) -> dict | None: ...
    def write(self, target: str, username: str, secret: str, comment: str) -> None: ...
    def delete(self, target: str) -> None: ...


class WindowsCredentials:
    """Generic credentials in Windows Credential Manager (DPAPI-protected
    for this Windows user)."""

    def list(self, prefix: str) -> list[dict]:
        import win32cred

        try:
            found = win32cred.CredEnumerate(prefix + "*", 0) or []
        except Exception as exc:
            if getattr(exc, "winerror", None) == 1168:  # nothing saved yet
                return []
            raise VaultError("Windows Credential Manager could not be read.") from None
        return [{"target": item["TargetName"], "username": item.get("UserName") or "",
                 "comment": item.get("Comment") or ""} for item in found]

    def read(self, target: str) -> dict | None:
        import win32cred

        try:
            item = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            if getattr(exc, "winerror", None) == 1168:
                return None
            raise VaultError("Windows Credential Manager could not be read.") from None
        blob = item.get("CredentialBlob") or b""
        secret = blob.decode("utf-8") if isinstance(blob, bytes) else str(blob)
        return {"username": item.get("UserName") or "", "secret": secret, "comment": item.get("Comment") or ""}

    def write(self, target: str, username: str, secret: str, comment: str) -> None:
        import win32cred

        try:
            win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC, "TargetName": target, "UserName": username,
                                 "CredentialBlob": secret.encode("utf-8"), "Comment": comment,
                                 "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)
        except Exception:
            raise VaultError("The password could not be saved in Windows Credential Manager.") from None

    def delete(self, target: str) -> None:
        import win32cred

        try:
            win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            if getattr(exc, "winerror", None) != 1168:
                raise VaultError("The password could not be removed.") from None


class MemoryCredentials:
    """The same interface in memory, for tests."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def list(self, prefix: str) -> list[dict]:
        return [{"target": target, "username": item["username"], "comment": item["comment"]}
                for target, item in self.items.items() if target.startswith(prefix)]

    def read(self, target: str) -> dict | None:
        item = self.items.get(target)
        return dict(item) if item else None

    def write(self, target: str, username: str, secret: str, comment: str) -> None:
        self.items[target] = {"username": username, "secret": secret, "comment": comment}

    def delete(self, target: str) -> None:
        self.items.pop(target, None)


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().casefold())


class PasswordVault:
    def __init__(self, backend: CredentialBackend | None = None, profile_id: str = "default") -> None:
        self.backend = backend or WindowsCredentials()
        self.profile_id = profile_id
        self._lock = threading.Lock()

    def _prefix(self) -> str:
        return f"{TARGET_PREFIX}{self.profile_id}/"

    def _target(self, name: str) -> str:
        return self._prefix() + _key(name)

    @staticmethod
    def _clean_name(name: str) -> str:
        name = re.sub(r"\s+", " ", str(name or "")).strip()
        if not 1 <= len(name) <= MAX_NAME:
            raise VaultError(f"Give the password a name of up to {MAX_NAME} characters.")
        return name

    def entries(self) -> list[VaultEntry]:
        with self._lock:
            found = self.backend.list(self._prefix())
        entries = []
        for item in found:
            try:
                comment = json.loads(item["comment"]) if item["comment"] else {}
            except ValueError:
                comment = {}
            name = str(comment.get("name") or item["target"][len(self._prefix()):])
            entries.append(VaultEntry(name, item["username"], str(comment.get("updated") or "")))
        return sorted(entries, key=lambda entry: entry.name.casefold())

    def find(self, query: str) -> VaultEntry | None:
        """The entry whose name matches `query` exactly, else the only one containing it."""
        wanted = _key(query)
        entries = self.entries()
        exact = [entry for entry in entries if _key(entry.name) == wanted]
        if exact:
            return exact[0]
        partial = [entry for entry in entries if wanted and (wanted in _key(entry.name) or _key(entry.name) in wanted)]
        return partial[0] if len(partial) == 1 else None

    def save(self, name: str, secret: str, username: str = "") -> VaultEntry:
        name = self._clean_name(name)
        if not isinstance(secret, str) or not secret or len(secret) > MAX_SECRET:
            raise VaultError(f"A password must be 1 to {MAX_SECRET} characters.")
        username = str(username or "").strip()[:120]
        updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
        comment = json.dumps({"name": name, "updated": updated}, ensure_ascii=False)
        with self._lock:
            self.backend.write(self._target(name), username, secret, comment)
        return VaultEntry(name, username, updated)

    def reveal(self, name: str) -> tuple[VaultEntry, str] | None:
        """(entry, password) for showing it locally; never for an AI reply."""
        entry = self.find(name)
        if entry is None:
            return None
        with self._lock:
            item = self.backend.read(self._target(entry.name))
        return (entry, item["secret"]) if item else None

    def delete(self, name: str) -> VaultEntry | None:
        entry = self.find(name)
        if entry is None:
            return None
        with self._lock:
            self.backend.delete(self._target(entry.name))
        return entry


_SYMBOLS = {"@": "at", "#": "hash", "$": "dollar", "%": "percent", "&": "and", "*": "star", "-": "dash",
            "_": "underscore", ".": "dot", ",": "comma", "!": "exclamation mark", "?": "question mark",
            "+": "plus", "=": "equals", "/": "slash", "\\": "backslash", ":": "colon", ";": "semicolon",
            "(": "open bracket", ")": "close bracket", " ": "space", "'": "apostrophe", '"': "quote",
            "~": "tilde", "^": "caret", "<": "less than", ">": "greater than", "[": "open square bracket",
            "]": "close square bracket", "{": "open curly bracket", "}": "close curly bracket", "|": "bar",
            "`": "backtick"}


def spelled(secret: str) -> str:
    """How the local voice reads a password: one character at a time."""
    parts = []
    for char in secret:
        if char.isalpha() and char.isupper():
            parts.append(f"capital {char}")
        elif char.isalnum():
            parts.append(char)
        else:
            parts.append(_SYMBOLS.get(char, "symbol"))
    return ", ".join(parts)


def speak_locally(text: str) -> None:
    """Speak with the offline Windows voice (SAPI) on this thread; nothing
    leaves the computer."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voice.Rate = -3
        voice.Speak(text)
    finally:
        pythoncom.CoUninitialize()
