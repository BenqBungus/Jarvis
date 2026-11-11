"""Build and check a standalone Windows beta without developer PATH contamination."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PYTHON", "OPENAI"))}
    env["PATH"] = os.pathsep.join([str(Path(os.environ["WINDIR"]) / "System32"), os.environ["WINDIR"]])
    env["JARVIS_LOAD_USER_OPENAI_API_KEY"] = "0"
    subprocess.run([sys.executable, "-m", "PyInstaller", "installer/jarvis.spec", "--noconfirm",
                    "--distpath", "dist-desktop", "--workpath", "data/build-desktop"],
                   cwd=ROOT, env=env, check=True)
    package = ROOT / "dist-desktop" / "Jarvis"
    diagnostics = ROOT / "data" / "diagnostics" / "desktop-release"
    diagnostics.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(package / "Jarvis.exe"), "--package-check"], cwd=diagnostics,
                   env=env, check=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    report = json.loads((diagnostics / "package-check.json").read_text())
    if not report.get("ok"):
        raise RuntimeError("Packaged smoke check failed; no release ZIP created.")
    output = ROOT / "dist-beta" / "Jarvis-Windows-standalone-beta.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        hashes = {}
        for path in sorted(package.rglob("*")):
            if not path.is_file():
                continue
            if path.is_symlink() or package not in path.resolve().parents:
                raise ValueError("Unexpected package path")
            relative = path.relative_to(package)
            if any(part in {"data", "logs", ".env", ".venv", ".codex"} for part in relative.parts):
                raise ValueError("User state found in the package")
            archive.write(path, "Jarvis/" + relative.as_posix())
            hashes[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        guide = (ROOT / "docs" / "DESKTOP_BETA.txt").read_bytes()
        archive.writestr("Jarvis/START-HERE.txt", guide)
        hashes["START-HERE.txt"] = hashlib.sha256(guide).hexdigest()
        dependencies = ["PySide6", "PySide6-Essentials", "PySide6-Addons", "shiboken6", "openai",
            "python-docx", "pypdf", "pypdfium2", "Pillow", "pywin32", "comtypes", "pycaw",
            "send2trash", "websockets", "sounddevice", "PyAudio", "SpeechRecognition", "pyttsx3",
            "pocketsphinx", "psutil", "lxml", "pydantic", "pydantic_core", "httpx", "httpcore",
            "anyio", "sniffio", "certifi", "idna", "h11", "jiter", "typing_extensions", "distro"]
        dependencies += [d.metadata["Name"] for d in importlib.metadata.distributions()
                         if d.metadata["Name"].lower().startswith("winrt-")]
        versions = {}
        for name in sorted(set(dependencies)):
            try:
                distribution = importlib.metadata.distribution(name)
            except importlib.metadata.PackageNotFoundError:
                continue
            versions[name] = distribution.version
            for item in distribution.files or []:
                if not item.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                    continue
                source = distribution.locate_file(item)
                if not source.is_file() or source.stat().st_size > 2 * 1024 * 1024:
                    continue
                target = "THIRD-PARTY/" + name + "/" + str(item).replace("../", "").replace("\\", "/")
                data = source.read_bytes()
                archive.writestr("Jarvis/" + target, data)
                hashes[target] = hashlib.sha256(data).hexdigest()
        data = json.dumps(versions, indent=2).encode("utf-8")
        archive.writestr("Jarvis/THIRD-PARTY/versions.json", data)
        hashes["THIRD-PARTY/versions.json"] = hashlib.sha256(data).hexdigest()
        archive.writestr("Jarvis/MANIFEST.json", json.dumps(hashes, indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():
            raise RuntimeError("ZIP integrity check failed")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".sha256").write_text(digest + "  " + output.name + "\n", encoding="ascii")
    print(f"Ready: {output.name} ({output.stat().st_size / 1024 / 1024:.1f} MiB)")
    print("SHA256: " + digest)


if __name__ == "__main__":
    main()
