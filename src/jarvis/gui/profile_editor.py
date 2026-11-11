"""Profile editor, photo cropper and adult-PIN prompt.

Owned by Claude (docs/claude/PERSONALIZATION_HANDOFF.md, C3/C4). The dialogs
only collect choices. ProfileStore and the permission rules (Codex,
profiles.py / permission_levels.py) validate, store and enforce them, so a
PIN typed here is handed straight to a signal and never kept or logged.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from ..personality import DETAIL_LEVELS, HUMOR_LEVELS, PRESETS
from ..personality import normalize as normalize_personality
from ..role_packs import PACKS, normalize_packs
from .avatar import AvatarCropper, PHOTO_FILTER, generated_avatar, hue_for, load_image, photo_avatar, profile_hue
from .settings_page import SettingsPage, _Card, _ChoiceCard, _divider, _role_label, _ToggleSwitch
from .voice_core import AURORA, BASE_STYLE, FONT_DISPLAY, FONT_SEMIBOLD, card_rules

_A = AURORA

# What each level means to the person choosing it. The rules themselves
# live in permission_levels.py (Codex, X2); keep this copy in step with them.
LEVELS = {
    "adult": ("Adult", "Full Jarvis. Manages profiles and approves protected actions."),
    "kid": ("Kid", "Safe tools only: no power, network, driver, email or file-removal actions."),
    "guest": ("Guest", "Nothing personal: no memory, email or personal files, and nothing is learned."),
}
# Sensible starting points when a new profile's level is picked; any choice
# the person already made by hand is kept.
LEVEL_DEFAULTS = {
    "adult": {"preset": "jarvis", "role_packs": ["gamer"], "learn_habits": True},
    "kid": {"preset": "tutor", "role_packs": ["student"], "learn_habits": True},
    "guest": {"preset": "friend", "role_packs": [], "learn_habits": False},
}
LANGUAGES = (("English", "en"), ("Bulgarian (Български)", "bg"), ("Auto-detect", "auto"))
LIVE_VOICES = ("cedar", "marin")
HUES = (190, 265, 330, 25, 140, 45)  # swatches for generated avatars

EDITOR_STYLE = BASE_STYLE + card_rules("#profileEditor") + f"""
#profileEditor QScrollArea {{ background: transparent; border: none; }}
#profileEditor QScrollArea > QWidget > QWidget {{ background: transparent; }}
#profileEditor QFrame[role="previewPanel"] {{ background: rgba(14, 19, 25, 235); border: 1px solid {_A['border']};
    border-radius: 16px; }}
#profileEditor QLabel[role="dialogTitle"] {{ color: {_A['text']}; font-family: {FONT_DISPLAY}; font-weight: 600;
    font-size: 20px; }}
#profileEditor QLabel[role="dialogSubtitle"], #profileEditor QLabel[role="cardHint"] {{
    color: {_A['text_secondary']}; font-size: 12px; }}
#profileEditor QLabel[role="previewName"] {{ color: {_A['text']}; font-family: {FONT_DISPLAY}; font-weight: 600;
    font-size: 17px; }}
#profileEditor QLabel[role="previewLine"] {{ color: {_A['text_secondary']}; font-size: 12px; }}
#profileEditor QLabel[role="rowTitle"] {{ color: {_A['text']}; }}
#profileEditor QLabel[role="rowHint"] {{ color: {_A['text_tertiary']}; font-size: 12px; }}
#profileEditor QLabel[role="error"] {{ color: {_A['danger']}; font-size: 12px; }}
#profileEditor QLabel[role="levelBadge"] {{ border-radius: 10px; padding: 2px 10px; font-family: {FONT_SEMIBOLD};
    font-weight: 600; font-size: 10px; letter-spacing: 1px; background: rgba(34, 211, 238, 30);
    color: {_A['accent_light']}; border: 1px solid rgba(34, 211, 238, 105); }}
#profileEditor QLabel[role="levelBadge"][level="kid"] {{ background: rgba(139, 92, 246, 34); color: #C4B5FD;
    border-color: rgba(139, 92, 246, 105); }}
#profileEditor QLabel[role="levelBadge"][level="guest"] {{ background: {_A['card_hover']};
    color: {_A['text_secondary']}; border-color: {_A['border_strong']}; }}
#profileEditor QPushButton[role="swatch"] {{ border-radius: 11px; min-width: 22px; max-width: 22px; min-height: 22px;
    max-height: 22px; padding: 0; border: 2px solid transparent; }}
#profileEditor QPushButton[role="swatch"]:checked {{ border-color: {_A['text']}; }}
#profileEditor QPushButton[role="danger"] {{ color: {_A['danger']}; }}
#profileEditor QSlider::groove:horizontal {{ height: 4px; background: {_A['border_strong']}; border-radius: 2px; }}
#profileEditor QSlider::sub-page:horizontal {{ border-radius: 2px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {_A['accent']}, stop:1 {_A['accent_2']}); }}
#profileEditor QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 8px;
    background: {_A['text']}; border: 2px solid {_A['accent']}; }}
#profileEditor QLabel[role="sliderValue"] {{ color: {_A['text_secondary']}; font-size: 12px; }}
"""


def _swatch_style(hue: int) -> str:
    start, end = QColor.fromHsl(hue, 185, 132).name(), QColor.fromHsl((hue + 38) % 360, 170, 78).name()
    return f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {start}, stop:1 {end});"


def _primary(button: QPushButton) -> QPushButton:
    button.setProperty("variant", "primary")
    button.setDefault(True)
    return button


class PhotoCropDialog(QDialog):
    """Frame a chosen photo inside the avatar circle."""

    def __init__(self, image: QImage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("profileEditor")
        self.setStyleSheet(EDITOR_STYLE)
        self.setWindowTitle("Frame your photo")
        self.resize(420, 500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(_role_label("Frame your photo", "dialogTitle"))
        layout.addWidget(_role_label("Drag to move, scroll or use the slider to zoom.", "dialogSubtitle"))
        self.cropper = AvatarCropper(image)
        layout.addWidget(self.cropper, 1)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(100, round(AvatarCropper.MAX_ZOOM * 100))
        self.zoom_slider.valueChanged.connect(lambda value: self.cropper.set_zoom(value / 100))
        self.cropper.changed.connect(lambda: self._sync_slider())
        layout.addWidget(self.zoom_slider)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        use = _primary(QPushButton("Use photo"))
        use.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(use)
        layout.addLayout(buttons)

    def _sync_slider(self) -> None:
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(round(self.cropper.zoom * 100))
        self.zoom_slider.blockSignals(False)


class AdultPinDialog(QDialog):
    """Asks for the adult PIN (4-8 digits) to leave a Kid or Guest profile,
    or sets a new one (typed twice). The PIN goes to the caller only."""

    def __init__(self, parent: QWidget | None = None, *, profile_name: str = "", set_new: bool = False,
                 error: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("profileEditor")
        self.setStyleSheet(EDITOR_STYLE)
        self._set_new = set_new
        self.setWindowTitle("Set adult PIN" if set_new else "Adult PIN")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(_role_label("Set adult PIN" if set_new else "Adult PIN needed", "dialogTitle"))
        subtitle = ("Kid and Guest profiles need this PIN to switch to an adult profile. Use 4 to 8 digits."
                    if set_new else f"Enter the adult PIN to switch to {profile_name or 'this profile'}.")
        layout.addWidget(_role_label(subtitle, "dialogSubtitle", wrap=True))
        validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,8}"), self)
        self.pin_input = QLineEdit()
        self.pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin_input.setValidator(validator)
        self.pin_input.setPlaceholderText("PIN")
        self.pin_input.setAccessibleName("Adult PIN")
        layout.addWidget(self.pin_input)
        self.repeat_input = QLineEdit()
        self.repeat_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.repeat_input.setValidator(validator)
        self.repeat_input.setPlaceholderText("Repeat PIN")
        self.repeat_input.setAccessibleName("Repeat adult PIN")
        self.repeat_input.setVisible(set_new)
        layout.addWidget(self.repeat_input)
        self.error_label = _role_label(error, "error", wrap=True)
        self.error_label.setVisible(bool(error))
        layout.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok_button = _primary(QPushButton("Set PIN" if set_new else "Unlock"))
        self.ok_button.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok_button)
        layout.addLayout(buttons)
        self.resize(380, self.sizeHint().height())

    def pin(self) -> str:
        return self.pin_input.text()

    def _submit(self) -> None:
        pin = self.pin_input.text()
        if not (pin.isascii() and pin.isdigit() and 4 <= len(pin) <= 8):
            self._show_error("Use 4 to 8 digits.")
        elif self._set_new and pin != self.repeat_input.text():
            self._show_error("The two PINs are different.")
        else:
            self.accept()

    def _show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()

    @classmethod
    def ask(cls, parent: QWidget | None, profile_name: str = "", *, error: str = "") -> str | None:
        dialog = cls(parent, profile_name=profile_name, error=error)
        pin = dialog.pin() if dialog.exec() == QDialog.DialogCode.Accepted else None
        dialog.pin_input.clear()
        dialog.deleteLater()
        return pin


class ProfileEditorDialog(QDialog):
    """Create (profile=None) or edit one person's profile.

    On Save it emits `saved(changes)` first -- every field for a new profile,
    only the changed ones otherwise -- then `avatar_chosen(png)` when a new
    photo was framed (a 512x512 PNG for ProfileStore.set_avatar) and
    `adult_pin_chosen(pin)` when an adult set a new PIN. Returning to a
    generated avatar saves `"avatar": ""`."""

    saved = Signal(dict)
    avatar_chosen = Signal(bytes)
    adult_pin_chosen = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, profile: dict | None = None, parent: QWidget | None = None, *,
                 avatar_path: str | Path | None = None, can_manage: bool = True, windows_user: str = "",
                 default_language: str = "auto", pin_set: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("profileEditor")
        self.setStyleSheet(EDITOR_STYLE)
        self._profile = dict(profile or {})
        self._is_new = profile is None
        self._can_manage = can_manage
        self._windows_user = windows_user
        self._default_language = default_language
        self._pin_set = pin_set  # without an adult PIN, Kid and Guest profiles could just switch back
        self._photo = None if self._is_new else load_image(avatar_path)
        self._new_photo_png: bytes | None = None
        self._pending_pin: str | None = None
        self._hue = profile_hue(self._profile) if self._profile.get("display_name") else None
        self._customized: set[str] = set()
        self._applying = False
        name = str(self._profile.get("display_name") or "")
        self.setWindowTitle("New profile" if self._is_new else f"Edit profile · {name}")
        width, height = 900, 680
        screen = (parent.screen() if parent is not None else None) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width, height = min(width, max(640, available.width() - 60)), min(height, max(440, available.height() - 60))
        self.resize(width, height)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(_role_label("New profile" if self._is_new else "Edit profile", "dialogTitle"))
        titles.addWidget(_role_label(
            "Everyone gets their own Jarvis: name, look, personality, packs and what it may do."
            if self._is_new else "Changes apply as soon as you save.", "dialogSubtitle"))
        root.addLayout(titles)

        body = QHBoxLayout()
        body.setSpacing(20)
        body.addWidget(self._build_preview_panel(), 0, Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 10, 0)
        column.setSpacing(0)
        for group in (self._build_identity_card(), self._build_style_card(), self._build_packs_card(),
                      self._build_privacy_card()):
            column.addWidget(group)
        column.addStretch()
        scroll.setWidget(content)
        body.addWidget(scroll, 1)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        self.delete_button = QPushButton("Delete profile")
        self.delete_button.setProperty("role", "danger")
        self.delete_button.setVisible(not self._is_new and can_manage)
        self.delete_button.clicked.connect(self._request_delete)
        footer.addWidget(self.delete_button)
        footer.addStretch()
        self.error_label = _role_label("", "error")
        footer.addWidget(self.error_label)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.save_button = _primary(QPushButton("Create profile" if self._is_new else "Save"))
        self.save_button.clicked.connect(self._on_save)
        footer.addWidget(cancel)
        footer.addWidget(self.save_button)
        root.addLayout(footer)

        self._load()
        self._refresh_preview()

    # ------------------------------------------------------------ building

    def _build_preview_panel(self) -> QFrame:
        panel = QFrame()
        panel.setProperty("role", "previewPanel")
        panel.setFixedWidth(236)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 22, 20, 20)
        layout.setSpacing(8)
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(112, 112)
        self.avatar_label.setAccessibleName("Avatar preview")
        layout.addWidget(self.avatar_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(6)
        self.preview_name = _role_label("", "previewName")
        self.preview_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview_name)
        self.level_badge = _role_label("", "levelBadge")
        layout.addWidget(self.level_badge, 0, Qt.AlignmentFlag.AlignHCenter)
        self.preview_style = _role_label("", "previewLine", wrap=True)
        self.preview_style.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview_style)
        layout.addSpacing(8)
        self.photo_button = QPushButton("Choose photo…")
        self.photo_button.clicked.connect(self.choose_photo)
        layout.addWidget(self.photo_button)
        self.initials_button = QPushButton("Use initials instead")
        self.initials_button.setProperty("role", "ghost")
        self.initials_button.clicked.connect(self.use_generated_avatar)
        layout.addWidget(self.initials_button)
        swatches = QHBoxLayout()
        swatches.setSpacing(6)
        self._swatch_group = QButtonGroup(self)
        self._swatch_group.setExclusive(True)
        self.swatches: dict[int, QPushButton] = {}
        for hue in HUES:
            swatch = QPushButton()
            swatch.setProperty("role", "swatch")
            swatch.setCheckable(True)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setToolTip("Avatar color")
            swatch.setAccessibleName(f"Avatar color {hue}")
            swatch.setStyleSheet(_swatch_style(hue))
            swatch.clicked.connect(lambda _checked=False, value=hue: self._pick_hue(value))
            self._swatch_group.addButton(swatch)
            self.swatches[hue] = swatch
            swatches.addWidget(swatch)
        self._swatch_row = QWidget()
        self._swatch_row.setLayout(swatches)
        layout.addWidget(self._swatch_row, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        return panel

    def _build_identity_card(self):
        card = _Card("Who is it for?")
        grid_host = QWidget()
        grid = QVBoxLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 8)
        grid.setSpacing(8)
        self._level_group = QButtonGroup(self)
        self._level_group.setExclusive(True)
        self.level_cards: dict[str, _ChoiceCard] = {}
        for level, (title, description) in LEVELS.items():
            button = _ChoiceCard(title, description)
            button.setEnabled(self._can_manage)
            self._level_group.addButton(button)
            self.level_cards[level] = button
            button.toggled.connect(lambda checked, value=level: checked and self._on_level_picked(value))
            grid.addWidget(button)
        card.add(grid_host, divided=False)
        if not self._can_manage:
            card.note("Only an adult profile can change this.")
        self.name_input = QLineEdit()
        self.name_input.setMaxLength(32)
        self.name_input.setPlaceholderText("e.g. Берк")
        self.name_input.textChanged.connect(self._refresh_preview)
        card.row("Name", self.name_input, "Shown on the profile and used in greetings.")
        self.language_combo = QComboBox()
        for label, code in LANGUAGES:
            self.language_combo.addItem(label, code)
        card.row("Language", self.language_combo, "The language Jarvis speaks with this person.")
        return card.group

    def _build_style_card(self):
        card = _Card("Personality")
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self._preset_group = QButtonGroup(self)
        self._preset_group.setExclusive(True)
        self.preset_cards: dict[str, _ChoiceCard] = {}
        for index, preset in enumerate(PRESETS.values()):
            button = _ChoiceCard(preset.name, preset.tagline)
            self._preset_group.addButton(button)
            self.preset_cards[preset.id] = button
            button.clicked.connect(lambda _checked=False: self._customized.add("preset"))
            button.toggled.connect(lambda checked: checked and self._refresh_preview())
            grid.addWidget(button, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        card.add(grid_host, divided=False)
        self.humor_slider, humor_row = SettingsPage._level_slider(HUMOR_LEVELS)
        card.row("Humor", humor_row)
        self.detail_slider, detail_row = SettingsPage._level_slider(DETAIL_LEVELS)
        card.row("Detail", detail_row)
        self.address_input = QLineEdit()
        self.address_input.setMaxLength(40)
        self.address_input.setPlaceholderText("Their name")
        card.row("Call them", self.address_input, "A nickname or title, e.g. sir. Empty uses the name.")
        self.voice_combo = QComboBox()
        self.voice_combo.addItem("Same as Settings", "")
        for voice in LIVE_VOICES:
            self.voice_combo.addItem(voice.capitalize(), voice)
        card.row("Live voice", self.voice_combo, "Each person can have their own Jarvis voice.")
        return card.group

    def _build_packs_card(self):
        card = _Card("Role packs")
        card.note("Know-how and quick actions on the HUD. Packs never grant extra permissions.")
        self.pack_switches: dict[str, _ToggleSwitch] = {}
        for pack in PACKS.values():
            switch = _ToggleSwitch(pack.name)
            switch.clicked.connect(lambda _checked=False: self._customized.add("role_packs"))
            switch.toggled.connect(lambda _checked: self._refresh_preview())
            self.pack_switches[pack.id] = switch
            card.toggle(switch, pack.tagline)
        return card.group

    def _build_privacy_card(self):
        card = _Card("Privacy and sign-in")
        self.learn_switch = _ToggleSwitch("Learn habits and suggest routines")
        self.learn_switch.clicked.connect(lambda _checked=False: self._customized.add("learn_habits"))
        card.toggle(self.learn_switch, "Jarvis notices repeated actions and asks before automating anything.")
        self.windows_switch = _ToggleSwitch(f"Choose automatically for Windows user {self._windows_user}")
        if self._can_manage and self._windows_user:
            card.toggle(self.windows_switch, "Jarvis starts with this profile when that Windows user signs in.")
        # The PIN row comes and goes with the level, so it carries its own divider.
        self._pin_row = QWidget()
        block = QVBoxLayout(self._pin_row)
        block.setContentsMargins(0, 0, 0, 0)
        block.setSpacing(0)
        block.addWidget(_divider())
        row = QHBoxLayout()
        row.setContentsMargins(0, 9, 0, 9)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(_role_label("Adult PIN", "rowTitle"))
        self._pin_hint = _role_label("Needed to leave a Kid or Guest profile for an adult one.", "rowHint", wrap=True)
        text.addWidget(self._pin_hint)
        row.addLayout(text, 1)
        self.pin_button = QPushButton("Set PIN…")
        self.pin_button.clicked.connect(self._choose_pin)
        row.addWidget(self.pin_button, 0, Qt.AlignmentFlag.AlignVCenter)
        block.addLayout(row)
        card.add(self._pin_row, divided=False)
        return card.group

    # ------------------------------------------------------------- state

    def _load(self) -> None:
        self._applying = True
        profile = self._profile
        level = profile.get("permission_level") if profile.get("permission_level") in LEVELS else "adult"
        self.level_cards[level].setChecked(True)
        self.name_input.setText(str(profile.get("display_name") or ""))
        index = self.language_combo.findData(profile.get("language") or self._default_language)
        self.language_combo.setCurrentIndex(max(0, index))
        personality = normalize_personality(profile.get("personality"))
        if self._is_new:
            personality["preset"] = LEVEL_DEFAULTS[level]["preset"]
        self.preset_cards[personality["preset"]].setChecked(True)
        self.humor_slider.setValue(personality["humor"])
        self.detail_slider.setValue(personality["detail"])
        self.address_input.setText(personality["address_as"])
        voice = (profile.get("voice") or {}).get("live_voice", "") if isinstance(profile.get("voice"), dict) else ""
        self.voice_combo.setCurrentIndex(max(0, self.voice_combo.findData(voice)))
        packs = LEVEL_DEFAULTS[level]["role_packs"] if self._is_new else normalize_packs(profile.get("role_packs"))
        for pack_id, switch in self.pack_switches.items():
            switch.setChecked(pack_id in packs)
        learn = LEVEL_DEFAULTS[level]["learn_habits"] if self._is_new else bool(profile.get("learn_habits", True))
        self.learn_switch.setChecked(learn)
        bound = str(profile.get("windows_user") or "")
        self.windows_switch.setChecked(bool(bound) and bound.lower() == self._windows_user.lower())
        self._applying = False
        self._sync_level_rows(level)

    def _current_level(self) -> str:
        return next((level for level, card in self.level_cards.items() if card.isChecked()), "adult")

    def _on_level_picked(self, level: str) -> None:
        self._sync_level_rows(level)
        if self._is_new and not self._applying:
            defaults = LEVEL_DEFAULTS[level]
            self._applying = True
            if "preset" not in self._customized:
                self.preset_cards[defaults["preset"]].setChecked(True)
            if "role_packs" not in self._customized:
                for pack_id, switch in self.pack_switches.items():
                    switch.setChecked(pack_id in defaults["role_packs"])
            if "learn_habits" not in self._customized:
                self.learn_switch.setChecked(defaults["learn_habits"])
            self._applying = False
        self._refresh_preview()

    def _sync_level_rows(self, level: str) -> None:
        # Guests are never learned from; the PIN is set from an adult profile.
        self.learn_switch.setEnabled(level != "guest")
        if level == "guest":
            self.learn_switch.setChecked(False)
        needs_first_pin = level != "adult" and not self._pin_set
        self._pin_row.setVisible(self._can_manage and (level == "adult" or needs_first_pin))
        self._pin_hint.setText("Set it first: Kid and Guest profiles need it to switch back to an adult."
                               if needs_first_pin else "Needed to leave a Kid or Guest profile for an adult one.")

    def _pick_hue(self, hue: int) -> None:
        self._hue = hue
        self._refresh_preview()

    def _effective_hue(self) -> int:
        return self._hue if self._hue is not None else hue_for(self.name_input.text())

    def _refresh_preview(self, *_args) -> None:
        name = self.name_input.text().strip()
        level = self._current_level()
        if self._photo is not None:
            pixmap = photo_avatar(self._photo, 112)
        else:
            pixmap = generated_avatar(name, self._effective_hue(), 112)
        self.avatar_label.setPixmap(pixmap)
        self.initials_button.setVisible(self._photo is not None)
        self._swatch_row.setVisible(self._photo is None)
        hue = self._effective_hue()
        for value, swatch in self.swatches.items():
            swatch.setChecked(value == hue)
        self.preview_name.setText(name or "New profile")
        self.level_badge.setText(LEVELS[level][0].upper())
        if self.level_badge.property("level") != level:
            self.level_badge.setProperty("level", level)
            self.level_badge.style().unpolish(self.level_badge)
            self.level_badge.style().polish(self.level_badge)
        preset = next((PRESETS[key].name for key, card in self.preset_cards.items() if card.isChecked()), "")
        packs = [PACKS[key].name for key, switch in self.pack_switches.items() if switch.isChecked()]
        self.preview_style.setText(f"{preset}\n{' · '.join(packs) if packs else 'No packs'}")

    # ------------------------------------------------------------ actions

    def choose_photo(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Choose a photo", str(Path.home() / "Pictures"), PHOTO_FILTER)
        if path:
            self.frame_photo(path)

    def frame_photo(self, path: str | Path) -> bool:
        image = load_image(path)
        if image is None:
            self.error_label.setText("That file is not an image Jarvis can read.")
            return False
        dialog = PhotoCropDialog(image, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            self.set_photo_png(dialog.cropper.result_png())
        dialog.deleteLater()
        return accepted

    def set_photo_png(self, png: bytes) -> None:
        image = QImage.fromData(png, "PNG")
        if image.isNull():
            return
        self._new_photo_png = png
        self._photo = image
        self.error_label.clear()
        self._refresh_preview()

    def use_generated_avatar(self) -> None:
        self._photo = None
        self._new_photo_png = None
        self._refresh_preview()

    def _choose_pin(self) -> None:
        dialog = AdultPinDialog(self, set_new=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._pending_pin = dialog.pin()
            self.pin_button.setText("PIN set ✓")
        dialog.pin_input.clear()
        dialog.repeat_input.clear()
        dialog.deleteLater()

    def _request_delete(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        name = self._profile.get("display_name") or "this profile"
        answer = QMessageBox.warning(
            self, "Delete profile?",
            f"Delete {name}? Jarvis forgets this profile. Its memory, history and avatar move to "
            "data\\profiles\\.deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(str(self._profile.get("id") or ""))
            self.reject()

    def collected(self) -> dict:
        """Every field the dialog edits, as the profile record stores it."""
        level = self._current_level()
        personality = normalize_personality(self._profile.get("personality"))
        personality.update({
            "preset": next((key for key, card in self.preset_cards.items() if card.isChecked()), "jarvis"),
            "humor": self.humor_slider.value(), "detail": self.detail_slider.value(),
            "address_as": self.address_input.text().strip(),
        })
        voice = dict(self._profile.get("voice") or {}) if isinstance(self._profile.get("voice"), dict) else {}
        chosen_voice = self.voice_combo.currentData()
        if chosen_voice:
            voice["live_voice"] = chosen_voice
        else:
            voice.pop("live_voice", None)
        data = {
            "display_name": self.name_input.text().strip(),
            "language": self.language_combo.currentData(),
            "personality": personality,
            "role_packs": [key for key, switch in self.pack_switches.items() if switch.isChecked()],
            "learn_habits": self.learn_switch.isChecked() and level != "guest",
            "voice": voice,
            "avatar_hue": self._effective_hue(),
        }
        if self._can_manage:
            data["permission_level"] = level
            if self._windows_user:
                bound = str(self._profile.get("windows_user") or "")
                if self.windows_switch.isChecked():
                    data["windows_user"] = self._windows_user
                elif bound.lower() == self._windows_user.lower():
                    data["windows_user"] = ""
        if self._photo is None and (self._is_new or self._profile.get("avatar")):
            data["avatar"] = ""
        return data

    def _on_save(self) -> None:
        data = self.collected()
        if not data["display_name"]:
            self.error_label.setText("Give the profile a name.")
            self.name_input.setFocus()
            return
        if (self._can_manage and data.get("permission_level", "adult") != "adult" and not self._pin_set
                and not self._pending_pin):
            self.error_label.setText("Set an adult PIN first.")
            return
        changes = data if self._is_new else {key: value for key, value in data.items()
                                             if self._profile.get(key) != value}
        self.saved.emit(changes)
        if self._new_photo_png is not None:
            self.avatar_chosen.emit(self._new_photo_png)
        if self._pending_pin:
            self.adult_pin_chosen.emit(self._pending_pin)
            self._pending_pin = None
        self.accept()
