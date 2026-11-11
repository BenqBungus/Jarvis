from __future__ import annotations

from jarvis.gui.splash import StartupSplash


def test_startup_splash_progress_updates_status_and_bar(qapp):
    splash = StartupSplash()

    splash.set_progress(33, "CALIBRATING")

    assert splash._progress == 33
    assert splash._bar.value() == 33
    assert splash._status == "CALIBRATING"


def test_startup_splash_finish_sets_ready_and_hides(qapp):
    splash = StartupSplash()
    splash.show()

    splash.finish()

    assert splash._progress == 100
    assert splash._status == "READY"
    assert splash.isHidden()
