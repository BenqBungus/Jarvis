from __future__ import annotations

from jarvis.nitrosense import NitroSenseProbe, probe


def test_has_low_level_api_true_when_wmi_classes_present():
    result = NitroSenseProbe(
        app_installed=True, services_running=("ASMSvc",), wmi_classes_present=("AcerGamingFunction",)
    )
    assert result.has_low_level_api is True


def test_has_low_level_api_false_when_no_wmi_classes_present():
    result = NitroSenseProbe(app_installed=True, services_running=(), wmi_classes_present=())
    assert result.has_low_level_api is False


def test_has_low_level_api_is_independent_of_app_installed():
    # The whole point of the flag: "the app is installed" and "a low-level
    # WMI API is present" are two separate facts that can disagree.
    installed_no_api = NitroSenseProbe(app_installed=True, services_running=(), wmi_classes_present=())
    assert installed_no_api.has_low_level_api is False

    api_without_app = NitroSenseProbe(app_installed=False, services_running=(), wmi_classes_present=("AcerGenericMethod",))
    assert api_without_app.has_low_level_api is True


def test_probe_returns_a_well_typed_structured_result_without_raising():
    # Real subprocess/WMI calls -- mirrors the light smoke-test style
    # already used for monitoring/checks.py's read_internet().
    result = probe()
    assert isinstance(result, NitroSenseProbe)
    assert isinstance(result.app_installed, bool)
    assert isinstance(result.services_running, tuple)
    assert isinstance(result.wmi_classes_present, tuple)
    assert all(isinstance(name, str) for name in result.services_running)
    assert all(isinstance(name, str) for name in result.wmi_classes_present)
