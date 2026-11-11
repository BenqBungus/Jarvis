from __future__ import annotations

import os

WEBSITES: dict[str, str] = {
    "facebook": "https://www.facebook.com",
    "fb": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "insta": "https://www.instagram.com",
    "youtube": "https://www.youtube.com",
    "ютуб": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "chatgpt": "https://chatgpt.com",
    "openai": "https://chatgpt.com",
}

APP_ALIASES: dict[str, str] = {
    "notepad": "notepad.exe",
    "бележник": "notepad.exe",
    "calculator": "calc.exe",
    "калкулатор": "calc.exe",
    "settings": "ms-settings:",
    "настройки": "ms-settings:",
    "task manager": "taskmgr.exe",
    "диспечер": "taskmgr.exe",
    "opera": "opera.exe",
    "opera gx": "opera.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "explorer": "explorer.exe",
}

WAKE_WORDS = (
    "hey jarvis",
    "hi jarvis",
    "hello jarvis",
    "здравей jarvis",
    "здравей джарвис",
    "джарвис",
    "jarvis",
)


def ensure_openai_api_key_visible() -> bool:
    """Make a User-level Windows OPENAI_API_KEY visible to this process.

    `setx OPENAI_API_KEY ...` updates future processes, but apps launched
    from an already-running parent can miss it until that parent restarts.
    Reading the current user's Environment registry value fills that gap
    without printing or storing the key anywhere else.
    """
    if os.getenv("OPENAI_API_KEY"):
        return True
    if os.getenv("JARVIS_LOAD_USER_OPENAI_API_KEY", "1").strip().lower() in {"0", "false", "no"}:
        return False
    if os.name != "nt":
        return False
    from .credentials import load_api_key
    stored_key = load_api_key()
    if stored_key:
        os.environ["OPENAI_API_KEY"] = stored_key
        return True
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _value_type = winreg.QueryValueEx(key, "OPENAI_API_KEY")
    except OSError:
        return False
    value = str(value).strip()
    if not value:
        return False
    os.environ["OPENAI_API_KEY"] = value
    return True
