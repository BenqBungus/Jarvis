from __future__ import annotations

import sys
import os
from pathlib import Path

# Absolute import, deliberately not `from .app import main`: PyInstaller's
# Analysis() runs the target script with no package context (no __package__
# set, same as double-clicking a .py file), so a relative import here would
# silently fail to resolve during static analysis -- the build would
# "succeed" but only bundle the stdlib, since nothing past this line would
# ever get traced. src/jarvis/gui/__main__.py keeps the relative import;
# `python -m jarvis.gui` sets up proper package context and doesn't have
# this problem. This file exists only as the PyInstaller entry point.
if __name__ == "__main__":
    if "--package-check" in sys.argv:
        from jarvis.package_check import main as check
        sys.exit(check())
    if getattr(sys, "frozen", False):
        root = Path(os.environ["LOCALAPPDATA"]) / "Jarvis"
        root.mkdir(parents=True, exist_ok=True)
        os.chdir(root)
    from jarvis.gui.app import main
    sys.exit(main())
