from __future__ import annotations

import sys

import pytest

from jarvis import cli


def test_build_parser_recognizes_gui_flag():
    args = cli.build_parser().parse_args(["--gui"])
    assert args.gui is True


def test_build_parser_recognizes_audio_diagnostic_flags():
    args = cli.build_parser().parse_args(
        [
            "--list-audio-devices",
            "--test-speaker",
            "--test-output-tone",
            "--voice-doctor",
            "--audio-output-device",
            "17",
            "--set-audio-output-device",
            "17",
        ]
    )
    assert args.list_audio_devices is True
    assert args.test_speaker is True
    assert args.test_output_tone is True
    assert args.voice_doctor is True
    assert args.audio_output_device == "17"
    assert args.set_audio_output_device == "17"


def test_gui_flag_defaults_to_false():
    args = cli.build_parser().parse_args([])
    assert args.gui is False


def test_main_routes_to_gui_app_main_when_gui_flag_set(monkeypatch):
    calls = []

    def fake_gui_main(dry_run=False):
        calls.append(dry_run)
        return 0

    monkeypatch.setattr("jarvis.gui.app.main", fake_gui_main)
    monkeypatch.setattr(sys, "argv", ["jarvis", "--gui", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert calls == [True]
    assert exc_info.value.code == 0


def test_main_passes_dry_run_false_by_default_in_gui_mode(monkeypatch):
    calls = []
    monkeypatch.setattr("jarvis.gui.app.main", lambda dry_run=False: calls.append(dry_run) or 0)
    monkeypatch.setattr(sys, "argv", ["jarvis", "--gui"])

    with pytest.raises(SystemExit):
        cli.main()

    assert calls == [False]


def test_main_does_not_construct_terminal_safety_policy_in_gui_mode(monkeypatch):
    # The whole point of branching before SafetyPolicy(...) is constructed:
    # a --gui process may have no terminal for its blocking input() to read
    # from at all. Confirm it's never even instantiated in this path.
    monkeypatch.setattr("jarvis.gui.app.main", lambda dry_run=False: 0)
    monkeypatch.setattr(sys, "argv", ["jarvis", "--gui"])

    def _fail_if_constructed(*args, **kwargs):
        raise AssertionError("SafetyPolicy must not be constructed in --gui mode")

    monkeypatch.setattr(cli, "SafetyPolicy", _fail_if_constructed)

    with pytest.raises(SystemExit):
        cli.main()


def test_list_voices_still_takes_priority_over_gui(monkeypatch):
    # --list-voices is checked first in main(); if both flags are somehow
    # passed together, listing voices and exiting must win, not launching
    # the GUI.
    gui_calls = []
    monkeypatch.setattr("jarvis.gui.app.main", lambda dry_run=False: gui_calls.append(True) or 0)
    monkeypatch.setattr(cli, "_list_voices", lambda: None)
    monkeypatch.setattr(sys, "argv", ["jarvis", "--gui", "--list-voices"])

    cli.main()  # must return normally, not SystemExit, since list-voices path just returns

    assert gui_calls == []


def test_list_audio_devices_takes_priority_over_gui(monkeypatch):
    gui_calls = []
    list_calls = []
    monkeypatch.setattr("jarvis.gui.app.main", lambda dry_run=False: gui_calls.append(True) or 0)
    monkeypatch.setattr(cli, "_list_audio_devices", lambda: list_calls.append(True))
    monkeypatch.setattr(sys, "argv", ["jarvis", "--gui", "--list-audio-devices"])

    cli.main()

    assert list_calls == [True]
    assert gui_calls == []


def test_test_speaker_takes_priority_over_gui(monkeypatch):
    gui_calls = []
    test_calls = []
    monkeypatch.setattr("jarvis.gui.app.main", lambda dry_run=False: gui_calls.append(True) or 0)
    monkeypatch.setattr(cli, "_test_speaker", lambda: test_calls.append(True))
    monkeypatch.setattr(sys, "argv", ["jarvis", "--gui", "--test-speaker"])

    cli.main()

    assert test_calls == [True]
    assert gui_calls == []


def test_test_output_tone_takes_priority_over_gui(monkeypatch):
    gui_calls = []
    tone_calls = []
    monkeypatch.setattr("jarvis.gui.app.main", lambda dry_run=False: gui_calls.append(True) or 0)
    monkeypatch.setattr(cli, "_test_output_tone", lambda: tone_calls.append(True))
    monkeypatch.setattr(sys, "argv", ["jarvis", "--gui", "--test-output-tone"])

    cli.main()

    assert tone_calls == [True]
    assert gui_calls == []


def test_voice_doctor_takes_priority_over_gui(monkeypatch):
    gui_calls = []
    doctor_calls = []
    monkeypatch.setattr("jarvis.gui.app.main", lambda dry_run=False: gui_calls.append(True) or 0)
    monkeypatch.setattr(cli, "_voice_doctor", lambda: doctor_calls.append(True))
    monkeypatch.setattr(sys, "argv", ["jarvis", "--gui", "--voice-doctor"])

    cli.main()

    assert doctor_calls == [True]
    assert gui_calls == []


def test_audio_output_override_is_visible_to_diagnostics(monkeypatch):
    seen = []
    monkeypatch.setenv("JARVIS_AUDIO_OUTPUT_DEVICE", "original")
    monkeypatch.setattr(cli, "_voice_doctor", lambda: seen.append(True))
    monkeypatch.setattr(sys, "argv", ["jarvis", "--audio-output-device", "17", "--voice-doctor"])

    cli.main()

    import os

    assert seen == [True]
    assert os.environ["JARVIS_AUDIO_OUTPUT_DEVICE"] == "17"


def test_set_audio_output_device_takes_priority_over_gui(monkeypatch):
    gui_calls = []
    set_calls = []
    monkeypatch.setattr("jarvis.gui.app.main", lambda dry_run=False: gui_calls.append(True) or 0)
    monkeypatch.setattr(cli, "_set_audio_output_device", lambda value: set_calls.append(value))
    monkeypatch.setattr(sys, "argv", ["jarvis", "--gui", "--set-audio-output-device", "default"])

    cli.main()

    assert set_calls == ["default"]
    assert gui_calls == []
