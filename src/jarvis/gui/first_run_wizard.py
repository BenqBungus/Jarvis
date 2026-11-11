from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from ..config import WAKE_WORDS
from ..user_settings import SETTINGS_PATH, JarvisSettings
from .voice_core import AURORA, BASE_STYLE, FONT_DISPLAY, FONT_SEMIBOLD, LogoMark

_BROWSER_CHOICES = ("", "opera_gx", "chrome", "edge")
_A = AURORA

WIZARD_STYLE = BASE_STYLE + f"""
#setupWizard > QWidget > QLabel {{ background: transparent; color: {_A['text']}; font-family: {FONT_DISPLAY};
    font-size: 22px; padding: 2px 0 10px 0; }}
#setupWizard QWizardPage {{ background: transparent; }}
#setupWizard QLabel[role="lead"] {{ color: {_A['text_secondary']}; font-size: 15px; }}
#setupWizard QLabel[role="body"] {{ color: {_A['text_secondary']}; }}
#setupWizard QLabel[role="caption"] {{ color: {_A['text_tertiary']}; font-family: {FONT_SEMIBOLD}; font-weight: 600;
    font-size: 10px; letter-spacing: 1.4px; }}
#setupWizard QLabel[tone="ok"] {{ color: {_A['success']}; }}
#setupWizard QLabel[tone="bad"] {{ color: {_A['warning']}; }}
#setupWizard QLabel[tone="note"] {{ color: {_A['text_secondary']}; }}
#setupWizard QListWidget#wakePhrases {{ background: transparent; border: none; padding: 0; }}
#setupWizard QListWidget#wakePhrases::item {{ background: rgba(34, 211, 238, 20); color: {_A['accent_light']};
    border: 1px solid rgba(34, 211, 238, 70); border-radius: 14px; padding: 5px 14px; margin: 4px; }}
#setupSteps {{ background: {_A['card']}; border: 1px solid {_A['border']}; border-radius: 14px; }}
#setupSteps QLabel[role="brand"] {{ color: {_A['text']}; font-family: {FONT_SEMIBOLD}; font-weight: 600; font-size: 14px; }}
#setupSteps QLabel[role="hint"] {{ color: {_A['text_tertiary']}; font-size: 11px; }}
"""


def _text(text: str, role: str = "body", *, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", role)
    label.setWordWrap(wrap)
    return label


def _set_tone(label: QLabel, tone: str) -> None:
    if label.property("tone") != tone:
        label.setProperty("tone", tone)
        label.style().unpolish(label)
        label.style().polish(label)


def _page_layout(page: QWizardPage) -> QVBoxLayout:
    layout = QVBoxLayout(page)
    # 9px left lines the content up with ClassicStyle's page title.
    layout.setContentsMargins(9, 4, 0, 0)
    layout.setSpacing(12)
    return layout


def needs_first_run_wizard(settings_path: Path = SETTINGS_PATH) -> bool:
    return not settings_path.exists()


class _WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Welcome to Jarvis")
        layout = _page_layout(self)
        layout.addWidget(
            _text(
                "This short setup checks that your microphone, speakers, and API key are ready, "
                "and lets you pick a preferred browser. You can re-run it any time from the tray menu.",
                "lead",
            )
        )
        layout.addStretch(1)


class _ApiKeyPage(QWizardPage):
    """Explicit opt-in key storage, never written to settings or logs."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("OpenAI API Key")
        layout = _page_layout(self)

        configured = bool(os.getenv("OPENAI_API_KEY"))
        status = "OPENAI_API_KEY is set." if configured else "OPENAI_API_KEY is not set."
        self._status_label = _text(("✓ " if configured else "✗ ") + status)
        _set_tone(self._status_label, "ok" if configured else "bad")
        layout.addWidget(self._status_label)

        explanation = _text("Use your own OpenAI API key for online voice and answers. API usage is billed separately. "
            "Save stores it in Windows Credential Manager for this Windows account, not in Jarvis files. "
            "Presence of a key does not verify billing or model access.")
        layout.addWidget(explanation)
        layout.addSpacing(4)
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("Paste your OpenAI API key")
        key_row.addWidget(self._key_input, 1)
        self._save_key_button = QPushButton("Save key")
        self._save_key_button.setProperty("variant", "primary")
        self._save_key_button.clicked.connect(self._save_key)
        key_row.addWidget(self._save_key_button)
        layout.addLayout(key_row)
        forget_row = QHBoxLayout()
        self._remove_key_button = QPushButton("Forget saved key")
        self._remove_key_button.clicked.connect(self._remove_key)
        forget_row.addWidget(self._remove_key_button)
        forget_row.addStretch(1)
        layout.addLayout(forget_row)
        layout.addStretch(1)

    def _save_key(self) -> None:
        from ..credentials import save_api_key
        value = self._key_input.text().strip()
        try:
            save_api_key(value)
        except Exception:
            self._status_label.setText("Could not save. Check the key format and Windows Credential Manager access.")
            _set_tone(self._status_label, "bad")
            return
        os.environ["OPENAI_API_KEY"] = value
        self._key_input.clear()
        self._status_label.setText("Key saved for this Windows account. API access is checked when you connect.")
        _set_tone(self._status_label, "ok")

    def _remove_key(self) -> None:
        from ..credentials import remove_api_key
        try:
            remove_api_key()
        except Exception:
            self._status_label.setText("Could not remove the saved credential.")
            _set_tone(self._status_label, "bad")
            return
        os.environ.pop("OPENAI_API_KEY", None)
        self._key_input.clear()
        self._status_label.setText("Saved Jarvis key removed. A separately configured Windows environment key is not deleted.")
        _set_tone(self._status_label, "note")

    def is_configured(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))


class _MicrophonePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Microphone")
        layout = _page_layout(self)

        self._device_list = QListWidget()
        layout.addWidget(_text("DETECTED INPUT DEVICES", "caption", wrap=False))
        layout.addWidget(self._device_list, 1)
        self._populate_devices()

        test_row = QHBoxLayout()
        test_button = QPushButton("Test microphone (say something)")
        test_button.clicked.connect(self._run_test)
        test_row.addWidget(test_button)
        self._result_label = _text("")
        test_row.addWidget(self._result_label, 1)
        layout.addLayout(test_row)

    def _populate_devices(self) -> None:
        try:
            import speech_recognition as sr

            names = sr.Microphone.list_microphone_names()
        except Exception:
            self._device_list.addItem("SpeechRecognition/PyAudio not installed -- pip install -e .[voice]")
            return
        if not names:
            self._device_list.addItem("No input devices detected.")
            return
        for name in names:
            self._device_list.addItem(name)

    def _run_test(self) -> None:
        from ..audio.speech_to_text import SpeechToText

        stt = SpeechToText()
        if not stt.available:
            self._result_label.setText("Microphone not available (missing extras or no device).")
            return
        self._result_label.setText("Listening...")
        stt.calibrate()
        heard = stt.listen_once(timeout=5.0, phrase_time_limit=6.0)
        self._result_label.setText(f"Heard: {heard.text}" if heard else "Did not hear anything.")


class _SpeakerPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Speaker / Voice")
        layout = _page_layout(self)
        layout.addWidget(_text("Jarvis will speak a short test phrase.", "lead"))

        test_row = QHBoxLayout()
        test_button = QPushButton("Test speaker")
        test_button.clicked.connect(self._run_test)
        test_row.addWidget(test_button)
        self._result_label = _text("")
        test_row.addWidget(self._result_label, 1)
        layout.addLayout(test_row)
        layout.addStretch(1)

    def _run_test(self) -> None:
        from ..audio.text_to_speech import TextToSpeech

        tts = TextToSpeech()
        if not tts.enabled:
            self._result_label.setText("Text-to-speech not available (missing extras).")
            return
        self._result_label.setText("Speaking...")
        spoken = tts.speak("Здравей, аз съм Джарвис. Hello, I am Jarvis.")
        self._result_label.setText("Done." if spoken else "Speech failed.")


class _WakeWordPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Wake Phrases")
        layout = _page_layout(self)
        layout.addWidget(_text("Jarvis reacts to any of these, said before a command:", "lead"))
        self._wake_list = QListWidget()
        self._wake_list.setObjectName("wakePhrases")
        # Chips: phrases flow left to right and wrap.
        self._wake_list.setViewMode(QListView.ViewMode.ListMode)
        self._wake_list.setFlow(QListView.Flow.LeftToRight)
        self._wake_list.setWrapping(True)
        self._wake_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._wake_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._wake_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for phrase in WAKE_WORDS:
            self._wake_list.addItem(phrase)
        layout.addWidget(self._wake_list, 1)

    def listed_phrases(self) -> set[str]:
        return {self._wake_list.item(i).text() for i in range(self._wake_list.count())}


class _PermissionsPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Filesystem Permissions")
        layout = _page_layout(self)
        layout.addWidget(_text("Jarvis keeps its settings, logs and your workspace here.", "lead"))
        self._status_labels: dict[str, QLabel] = {}
        for label, path in (
            ("data", Path("data")),
            ("logs", Path("logs")),
            ("workspace", Path.cwd()),
        ):
            ok = self._check_writable(path)
            icon = "✓" if ok else "✗"
            status_label = _text(f"{icon} {label}: {path}")
            _set_tone(status_label, "ok" if ok else "bad")
            self._status_labels[label] = status_label
            layout.addWidget(status_label)
        layout.addStretch(1)

    def is_writable(self, label: str) -> bool:
        return self._status_labels[label].text().startswith("✓")

    @staticmethod
    def _check_writable(path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            marker = path / ".jarvis_permission_check"
            marker.write_text("ok", encoding="utf-8")
            marker.unlink()
            return True
        except OSError:
            return False


class _BrowserPage(QWizardPage):
    def __init__(self, settings: JarvisSettings) -> None:
        super().__init__()
        self.setTitle("Preferred Browser")
        self._settings = settings
        outer = _page_layout(self)
        outer.addWidget(_text("Jarvis opens websites and searches in this browser. Leave it empty for the system default.",
                              "lead"))
        layout = QFormLayout()
        layout.setHorizontalSpacing(16)
        self._browser_combo = QComboBox()
        self._browser_combo.setEditable(True)
        self._browser_combo.addItems(_BROWSER_CHOICES)
        self._browser_combo.setCurrentText(settings.preferred_browser)
        self._browser_combo.setMinimumWidth(240)
        layout.addRow("Browser", self._browser_combo)
        outer.addLayout(layout)
        outer.addStretch(1)

    def selected_browser(self) -> str:
        return self._browser_combo.currentText().strip().lower()


class _FinishPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("All Set")
        layout = _page_layout(self)
        layout.addWidget(_text("Setup complete. You can re-run this wizard any time from the tray menu.", "lead"))
        layout.addStretch(1)


class _StepRow(QWidget):
    """One stepper entry: a numbered (or checked) node on a vertical track."""

    def __init__(self, number: int, title: str, first: bool, last: bool) -> None:
        super().__init__()
        self._number = number
        self._title = title
        self._first = first
        self._last = last
        self._state = "upcoming"
        self.setFixedHeight(38)

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(160, 38)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_x, center_y, radius = 13.0, self.height() / 2, 11.0
        done = self._state == "done"
        current = self._state == "current"
        # The track is lit up to the current step.
        if not self._first:
            painter.setPen(QPen(QColor(_A["accent"] if done or current else _A["border_strong"]), 2))
            painter.drawLine(int(center_x), 0, int(center_x), int(center_y - radius - 3))
        if not self._last:
            painter.setPen(QPen(QColor(_A["accent"] if done else _A["border_strong"]), 2))
            painter.drawLine(int(center_x), int(center_y + radius + 3), int(center_x), self.height())

        node = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        if done:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(_A["accent"]))
            painter.drawEllipse(node)
            painter.setPen(QColor("#04131A"))
            painter.drawText(node, Qt.AlignmentFlag.AlignCenter, "✓")
        else:
            painter.setBrush(QColor(_A["card"]))
            painter.setPen(QPen(QColor(_A["accent"] if current else _A["border_strong"]), 1.5))
            painter.drawEllipse(node.adjusted(0.75, 0.75, -0.75, -0.75))
            painter.setPen(QColor(_A["accent_light"] if current else _A["text_tertiary"]))
            painter.drawText(node, Qt.AlignmentFlag.AlignCenter, str(self._number))

        text_font = QFont(self.font())
        text_font.setPixelSize(13)
        if current:
            text_font.setFamily("Segoe UI Variable Text Semibold")
        painter.setFont(text_font)
        painter.setPen(QColor(_A["text"] if current else _A["text_secondary"] if done else _A["text_tertiary"]))
        painter.drawText(QRectF(36, 0, self.width() - 36, self.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._title)
        painter.end()


class _StepRail(QWidget):
    """The wizard's side widget: brand plus a stepper that follows the pages."""

    def __init__(self, titles: list[str]) -> None:
        super().__init__()
        self.setObjectName("setupSteps")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 16, 18)
        layout.setSpacing(0)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(LogoMark())
        title = QLabel("Jarvis setup")
        title.setProperty("role", "brand")
        brand.addWidget(title, 1)
        layout.addLayout(brand)
        layout.addSpacing(22)
        self._rows = [_StepRow(index + 1, text, index == 0, index == len(titles) - 1)
                      for index, text in enumerate(titles)]
        for row in self._rows:
            layout.addWidget(row)
        layout.addStretch(1)
        hint = QLabel("Re-run any time from the tray menu.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def set_current(self, index: int) -> None:
        for position, row in enumerate(self._rows):
            row.set_state("done" if position < index else "current" if position == index else "upcoming")


class FirstRunWizard(QWizard):
    def __init__(self, settings: JarvisSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Jarvis Setup")
        self.setObjectName("setupWizard")
        # QWizard defaults to native AeroStyle on Windows, which draws part of
        # its chrome via DWM composition that resists QSS theming entirely --
        # ClassicStyle is the variant that actually respects a QSS background
        # (verified visually: ModernStyle's page body stayed native gray even
        # with an explicit QWizardPage rule in the stylesheet, because its
        # banner/watermark area is drawn by the style engine, not normal
        # widget painting).
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        for which, text in ((QWizard.WizardButton.BackButton, "Back"), (QWizard.WizardButton.NextButton, "Next"),
                            (QWizard.WizardButton.FinishButton, "Finish"), (QWizard.WizardButton.CancelButton, "Cancel")):
            self.setButtonText(which, text)
        # Before setStyleSheet(): the buttons already exist and are polished by it.
        for which in (QWizard.WizardButton.NextButton, QWizard.WizardButton.FinishButton):
            self.button(which).setProperty("variant", "primary")
        self.setStyleSheet(WIZARD_STYLE)
        self._soften_bottom_ruler()
        self._settings = settings

        self._welcome_page = _WelcomePage()
        self._api_key_page = _ApiKeyPage()
        self._microphone_page = _MicrophonePage()
        self._speaker_page = _SpeakerPage()
        self._wake_word_page = _WakeWordPage()
        self._permissions_page = _PermissionsPage()
        self._browser_page = _BrowserPage(settings)
        self._finish_page = _FinishPage()

        for page in (
            self._welcome_page,
            self._api_key_page,
            self._microphone_page,
            self._speaker_page,
            self._wake_word_page,
            self._permissions_page,
            self._browser_page,
            self._finish_page,
        ):
            self.addPage(page)

        # Kept on self: QWizard doesn't take Python ownership of the side
        # widget, and a temporary here is garbage-collected (and crashes).
        self._step_rail = _StepRail(["Welcome", "API key", "Microphone", "Speaker", "Wake phrases",
                                     "Permissions", "Browser", "Finish"])
        self.setSideWidget(self._step_rail)
        self.currentIdChanged.connect(self._on_page_changed)
        self._step_rail.set_current(0)
        self.resize(820, 540)

    def _soften_bottom_ruler(self) -> None:
        """ClassicStyle's separator above the buttons is an unnamed plain QWidget
        painted from the system palette (a bright line on light-mode Windows).
        It's the only plain QWidget among the wizard container's children; if
        Qt ever changes that, this simply finds nothing."""
        for container in self.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            for child in container.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                if child.metaObject().className() == "QWidget":
                    child.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                    child.setStyleSheet(f"background: {_A['border']};")
                    child.setFixedHeight(1)

    def _on_page_changed(self, page_id: int) -> None:
        ids = self.pageIds()
        if page_id in ids:
            self._step_rail.set_current(ids.index(page_id))

    def accept(self) -> None:  # noqa: N802 - Qt override signature
        self._settings.preferred_browser = self._browser_page.selected_browser()
        from .settings_io import save_settings

        save_settings(self._settings)
        super().accept()
