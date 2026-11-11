"""Jarvis-only, current-user Windows Credential Manager storage."""
TARGET = "Jarvis/OpenAI/APIKey"


def save_api_key(value: str) -> None:
    import win32cred
    value = value.strip()
    if not value.startswith("sk-") or not 20 <= len(value) <= 1024 or any(c.isspace() for c in value):
        raise ValueError("Enter a complete API key, without spaces.")
    win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC, "TargetName": TARGET,
        "UserName": "Jarvis", "CredentialBlob": value.encode("utf-16-le"),
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)


def load_api_key() -> str:
    try:
        import win32cred
        stored = win32cred.CredRead(TARGET, win32cred.CRED_TYPE_GENERIC, 0)["CredentialBlob"]
        return stored.decode("utf-16-le") if isinstance(stored, bytes) else stored
    except Exception:
        return ""


def remove_api_key() -> None:
    import win32cred
    import pywintypes
    try:
        win32cred.CredDelete(TARGET, win32cred.CRED_TYPE_GENERIC, 0)
    except pywintypes.error as exc:
        if getattr(exc, "winerror", None) != 1168:
            raise
