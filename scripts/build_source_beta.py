"""Build an allowlisted source-only beta; never copy developer state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(rb"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}")


def build(root=ROOT, destination=None):
    root = Path(root).resolve()
    destination = Path(destination or root / "dist-beta" / "Jarvis-source-beta-2026-09-11.zip").resolve()
    if root not in destination.parents:
        raise ValueError("Beta output must remain in the workspace.")
    inputs = {str(path.relative_to(root)).replace("\\", "/"): path
              for path in (root / "src" / "jarvis").rglob("*.py")
              if "__pycache__" not in path.parts}
    for name in ("pyproject.toml", "requirements.txt", "run.ps1"):
        inputs[name] = root / name
    inputs["BETA_TESTING.md"] = root / "docs" / "BETA_TESTING.md"
    inputs["FEATURES.md"] = root / "docs" / "SCREEN_AND_TRUSTED_ACCESS.md"
    for name in ("Start-Jarvis.cmd", "Setup-Jarvis.cmd"):
        inputs[name] = root / "scripts" / "beta" / name
    payloads = {}
    for name, path in sorted(inputs.items()):
        if path.is_symlink() or root not in path.resolve().parents:
            raise ValueError("Source path escaped workspace: " + name)
        data = path.read_bytes()
        if SECRET.search(data):
            raise ValueError("Possible hardcoded API secret in " + name + "; beta not built.")
        if name.endswith(".py"):
            compile(data, name, "exec")
        if name.endswith(".cmd"):
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        payloads[name] = data
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    payloads["MANIFEST.json"] = json.dumps(manifest, indent=2).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr("Jarvis-beta/" + name, data)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("Beta ZIP failed integrity verification.")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".sha256").write_text(digest + "  " + destination.name + "\n", encoding="ascii")
    print(f"Built {destination.name}: {len(payloads)} files, {destination.stat().st_size} bytes")
    print("SHA256: " + digest)
    return destination


if __name__ == "__main__":
    build()
