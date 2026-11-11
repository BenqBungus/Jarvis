"""Avatars (gui/avatar.py), the profile editor and the adult-PIN prompt
(gui/profile_editor.py). The store behind them is Codex's (profiles.py), so
these only check what the dialogs collect and emit."""
from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QDialog

from jarvis.gui.avatar import (
    AVATAR_SIZE, AvatarCropper, avatar_pixmap, generated_avatar, hue_for, initials, profile_hue, square_png,
)
from jarvis.gui.profile_editor import LEVEL_DEFAULTS, LEVELS, AdultPinDialog, ProfileEditorDialog
from jarvis.personality import PRESETS
from jarvis.role_packs import PACKS

_BERK = {"id": "berk", "display_name": "Берк", "avatar": "avatar.png", "avatar_hue": 190, "windows_user": "Berk",
         "language": "bg", "personality": {"preset": "jarvis", "humor": 1, "detail": 1, "address_as": "sir"},
         "role_packs": ["gamer"], "permission_level": "adult", "learn_habits": True,
         "voice": {"live_voice": "cedar"}}


def _halves(width=800, height=400) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ff0000"))
    for x in range(width // 2, width):
        for y in range(height):
            image.setPixelColor(x, y, QColor("#0000ff"))
    return image


def test_initials_and_stable_hues():
    assert initials("Берк") == "Б"
    assert initials("ана мария") == "АМ"
    assert initials("  x-y ") == "XY"
    assert initials("") == "?"
    assert hue_for("Берк") == hue_for(" берк ") and 0 <= hue_for("Берк") < 360
    assert profile_hue({"display_name": "Берк", "avatar_hue": 400}) == 40
    assert profile_hue({"display_name": "Берк"}) == hue_for("Берк")


def test_generated_and_photo_avatars(qapp, tmp_path):
    pixmap = generated_avatar("Берк", 190, 40)
    assert pixmap.devicePixelRatio() == 2.0 and pixmap.width() == 80
    image = pixmap.toImage()
    assert image.pixelColor(2, 2).alpha() == 0  # a disc, not a square
    assert image.pixelColor(40, 10).alpha() == 255
    path = tmp_path / "avatar.png"
    _halves(64, 64).save(str(path))
    photo = avatar_pixmap({"display_name": "Берк"}, path, 32).toImage()
    assert photo.pixelColor(12, 32).red() > 200 and photo.pixelColor(52, 32).blue() > 200
    missing = avatar_pixmap({"display_name": "Берк"}, tmp_path / "missing.png", 32)
    assert missing.toImage() == generated_avatar("Берк", hue_for("Берк"), 32).toImage()


def test_square_png_keeps_the_centered_square(qapp):
    png = square_png(_halves())
    image = QImage.fromData(png, "PNG")
    assert (image.width(), image.height()) == (AVATAR_SIZE, AVATAR_SIZE)
    assert image.pixelColor(100, 256).red() > 200 and image.pixelColor(400, 256).blue() > 200


def test_cropper_zooms_pans_and_stays_inside_the_photo(qapp):
    cropper = AvatarCropper(_halves())
    cropper.resize(300, 300)
    assert cropper.crop_rect().getRect() == (200.0, 0.0, 400.0, 400.0)
    cropper.set_zoom(2.0)
    assert cropper.crop_rect().width() == 200
    cropper.pan_by(QPointF(10_000, 0))  # dragging right moves the view to the photo's left edge
    assert cropper.crop_rect().left() == 0
    cropper.set_zoom(99)
    assert cropper.zoom == AvatarCropper.MAX_ZOOM
    left = QImage.fromData(cropper.result_png(64), "PNG")
    assert left.width() == 64 and left.pixelColor(32, 32).red() > 200


def test_new_profile_starts_from_the_chosen_level(qapp):
    dialog = ProfileEditorDialog(None, windows_user="Berk")
    assert dialog.level_cards["adult"].isChecked()
    assert dialog.preset_cards[LEVEL_DEFAULTS["adult"]["preset"]].isChecked()
    dialog.level_cards["kid"].click()
    assert dialog.preset_cards["tutor"].isChecked()
    assert [key for key, switch in dialog.pack_switches.items() if switch.isChecked()] == ["student"]
    dialog.pack_switches["gamer"].click()  # a choice made by hand is kept
    dialog.level_cards["guest"].click()
    assert dialog.preset_cards["friend"].isChecked()
    assert dialog.pack_switches["gamer"].isChecked() and dialog.pack_switches["student"].isChecked()
    assert not dialog.learn_switch.isChecked() and not dialog.learn_switch.isEnabled()
    assert dialog.level_badge.text() == "GUEST"


def test_a_new_profile_needs_a_name_and_saves_every_field(qapp):
    dialog = ProfileEditorDialog(None, windows_user="Berk")
    saved = []
    dialog.saved.connect(saved.append)
    dialog._on_save()
    assert saved == [] and dialog.error_label.text()
    dialog.name_input.setText("  Ани ")
    dialog.level_cards["kid"].click()
    dialog.windows_switch.setChecked(True)
    dialog._on_save()
    data = saved[-1]
    assert data["display_name"] == "Ани" and data["permission_level"] == "kid"
    assert data["personality"]["preset"] == "tutor" and data["role_packs"] == ["student"]
    assert data["windows_user"] == "Berk" and data["avatar"] == "" and data["language"] == "auto"
    assert set(data) >= {"learn_habits", "voice", "avatar_hue"}
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_editing_emits_only_changes_then_the_new_photo(qapp):
    dialog = ProfileEditorDialog(_BERK, windows_user="Berk")
    assert dialog.windows_switch.isChecked()
    assert dialog.address_input.text() == "sir"
    events = []
    dialog.saved.connect(lambda changes: events.append(("saved", changes)))
    dialog.avatar_chosen.connect(lambda png: events.append(("avatar", len(png))))
    dialog.preset_cards["coach"].click()
    dialog.pack_switches["student"].setChecked(True)
    dialog.set_photo_png(square_png(_halves(), size=AVATAR_SIZE))
    dialog._on_save()
    kind, changes = events[0]
    assert kind == "saved"
    assert changes["personality"]["preset"] == "coach" and changes["personality"]["address_as"] == "sir"
    assert changes["role_packs"] == ["gamer", "student"]
    assert not {"display_name", "language", "permission_level", "windows_user", "avatar", "voice"} & set(changes)
    assert events[1][0] == "avatar" and events[1][1] > 1000


def test_going_back_to_initials_clears_the_stored_photo(qapp, tmp_path):
    path = tmp_path / "avatar.png"
    _halves(64, 64).save(str(path))
    dialog = ProfileEditorDialog(_BERK, avatar_path=path)
    assert dialog.initials_button.isVisibleTo(dialog) and not dialog._swatch_row.isVisibleTo(dialog)
    saved = []
    dialog.saved.connect(saved.append)
    dialog.use_generated_avatar()
    dialog.swatches[265].click()
    dialog._on_save()
    assert saved[-1]["avatar"] == "" and saved[-1]["avatar_hue"] == 265


def test_non_adults_cannot_change_level_binding_pin_or_delete(qapp):
    kid = dict(_BERK, id="ani", display_name="Ани", permission_level="kid", windows_user="")
    dialog = ProfileEditorDialog(kid, can_manage=False, windows_user="Berk")
    assert not any(card.isEnabled() for card in dialog.level_cards.values())
    assert not dialog.delete_button.isVisibleTo(dialog)
    assert not dialog._pin_row.isVisibleTo(dialog)
    assert dialog.windows_switch.parentWidget() is None or not dialog.windows_switch.isVisibleTo(dialog)
    assert "permission_level" not in dialog.collected() and "windows_user" not in dialog.collected()


def test_adult_pin_is_emitted_only_on_save(qapp, monkeypatch):
    dialog = ProfileEditorDialog(_BERK)
    pins = []
    dialog.adult_pin_chosen.connect(pins.append)
    monkeypatch.setattr(AdultPinDialog, "exec", lambda self: (self.pin_input.setText("2468"),
                                                              QDialog.DialogCode.Accepted)[1])
    dialog._choose_pin()
    assert pins == [] and "✓" in dialog.pin_button.text()
    dialog._on_save()
    assert pins == ["2468"]


def test_pin_dialog_validates_before_accepting(qapp):
    dialog = AdultPinDialog(None, set_new=True)
    for bad in ("123", "12a4", "١٢٣٤"):  # too short, a letter, non-ASCII digits
        dialog.pin_input.setText(bad)
        dialog.repeat_input.setText(bad)
        dialog._submit()
        assert "4 to 8" in dialog.error_label.text() and dialog.result() != QDialog.DialogCode.Accepted
    dialog.pin_input.setText("1234")
    dialog.repeat_input.setText("1243")
    dialog._submit()
    assert "different" in dialog.error_label.text()
    dialog.repeat_input.setText("1234")
    dialog._submit()
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.pin() == "1234"


def test_level_copy_and_defaults_cover_every_level():
    assert set(LEVELS) == set(LEVEL_DEFAULTS) == {"adult", "kid", "guest"}
    for defaults in LEVEL_DEFAULTS.values():
        assert defaults["preset"] in PRESETS
        assert set(defaults["role_packs"]) <= set(PACKS)
    assert LEVEL_DEFAULTS["guest"]["learn_habits"] is False
