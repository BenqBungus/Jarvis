"""Console-free execution for Jarvis-owned helpers, never for user-launched apps."""
from __future__ import annotations

import os
import subprocess


def background_process_options() -> dict:
    options: dict = {"stdin": subprocess.DEVNULL}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return options


def powershell_command(script: str) -> list[str]:
    # Pipes must agree on encoding, including Bulgarian app names and results.
    encoded_script = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false);\n" + script
    return ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
            "-ExecutionPolicy", "Bypass", "-Command", encoded_script]
