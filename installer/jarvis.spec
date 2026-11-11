# -*- mode: python ; coding: utf-8 -*-
#
# Build with (from the repo root, after `pip install pyinstaller`):
#   pyinstaller installer/jarvis.spec --noconfirm
#
# Produces dist/Jarvis/Jarvis.exe (--onedir, not --onefile: a one-file build
# self-extracts to a fresh temp directory on every launch, which is bad
# startup latency for something meant to auto-start at login -- see
# gui/autostart.py). --noupx avoids upx-packed binaries, which materially
# raise antivirus false-positive rates for an unsigned indie exe.
#
# gui/app.py sets comtypes.client.gen_dir = None at import time so pycaw's
# volume control and pyttsx3's SAPI5 driver never try to disk-cache
# generated COM wrappers inside this bundle. python-docx's bundled
# docx/templates/default.docx and pyttsx3's platform driver module are
# pulled in automatically by pyinstaller-hooks-contrib's hook-docx.py /
# hook-pyttsx3.py -- verify both landed in dist/Jarvis/ after a build
# rather than assuming it (see README's packaging section).

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

REPO_ROOT = Path(SPECPATH).resolve().parent
SRC_DIR = REPO_ROOT / "src"

a = Analysis(
    [str(REPO_ROOT / "installer" / "entrypoint.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=collect_data_files("pocketsphinx"),
    hiddenimports=collect_submodules("winrt") + ["win32cred", "pyttsx3.drivers.sapi5"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "torch", "IPython", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Jarvis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)

worker = Analysis(
    [str(REPO_ROOT / "installer" / "document_entrypoint.py")],
    pathex=[str(SRC_DIR)],
    binaries=collect_dynamic_libs("pypdfium2_raw"),
    datas=[], hiddenimports=collect_submodules("winrt"),
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "torch", "IPython", "pytest"],
    noarchive=False,
)
worker_exe = EXE(PYZ(worker.pure), worker.scripts, [], exclude_binaries=True,
    name="JarvisDocumentWorker", console=True, upx=False)

# Qt uses Windows' native ICU. A developer PATH can accidentally supply
# Poppler's incompatible DLL with the same name. Do not redistribute it.
# Keep all bundled VC runtime copies at the version supplied with Qt.
import PySide6
qt_dir = Path(PySide6.__file__).parent
runtime_names = {"msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll"}
def normalized_binaries(entries):
    result = []
    for destination, source, kind in entries:
        name = Path(destination).name.lower()
        if name == "icuuc.dll" or name.startswith("icudt"):
            continue
        replacement = qt_dir / Path(destination).name
        if name in runtime_names and replacement.is_file():
            source = str(replacement)
        result.append((destination, source, kind))
    return result

coll = COLLECT(
    exe,
    worker_exe,
    normalized_binaries(a.binaries),
    a.datas,
    normalized_binaries(worker.binaries),
    worker.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Jarvis",
)
