import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import shutil


ROOT = Path(__file__).resolve().parents[1]


def test_clean_beta_manifest_and_extracted_cli(tmp_path):
    spec = importlib.util.spec_from_file_location("beta_builder", ROOT / "scripts" / "build_source_beta.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = tmp_path / "project"
    shutil.copytree(ROOT / "src", fixture / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "requirements.txt", "run.ps1", "docs/BETA_TESTING.md",
                 "docs/SCREEN_AND_TRUSTED_ACCESS.md", "scripts/beta/Start-Jarvis.cmd", "scripts/beta/Setup-Jarvis.cmd"):
        target = fixture / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    archive_path = module.build(fixture, fixture / "beta.zip")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert all(n.startswith("Jarvis-beta/") and ".." not in Path(n).parts for n in names)
        assert not any(any(p in {"data", ".env", ".venv", "logs", "__pycache__"} for p in Path(n).parts) for n in names)
        manifest = json.loads(archive.read("Jarvis-beta/MANIFEST.json"))
        for name, digest in manifest.items():
            assert hashlib.sha256(archive.read("Jarvis-beta/" + name)).hexdigest() == digest
        archive.extractall(tmp_path / "unpacked")
    root = tmp_path / "unpacked" / "Jarvis-beta"
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    env.update(PYTHONPATH=str(root / "src"), JARVIS_LOAD_USER_OPENAI_API_KEY="0", PYTHONDONTWRITEBYTECODE="1")
    help_result = subprocess.run([sys.executable, "-m", "jarvis", "--help"], cwd=root,
        env=env, capture_output=True, text=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert help_result.returncode == 0, help_result.stderr
    assert "--gui" in help_result.stdout
    from docx import Document
    import io
    document = Document()
    document.add_paragraph("Beta document extraction is working.")
    data = io.BytesIO()
    document.save(data)
    parsed = subprocess.run([sys.executable, "-m", "jarvis.document_extract", ".docx"], cwd=root,
        env=env, input=data.getvalue(), capture_output=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert parsed.returncode == 0, parsed.stderr
    assert json.loads(parsed.stdout)["ok"]
