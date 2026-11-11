"""Connects profiles, permission levels and habits to the running app.

X4 of docs/claude/PERSONALIZATION_HANDOFF.md, built by Claude on the user's
decision of 2026-09-25. app.py calls wire_profiles() once; everything else
lives here, so Claude and Codex rarely edit the same lines of app.py.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from ..gmail_auth import TARGET as GMAIL_TARGET
from ..gmail_auth import GmailCredentialStore
from ..habits import HabitLearner
from ..models import CommandResult
from ..permission_levels import LevelGate, full_access_allowed, normalize_level
from ..profiles import PROFILES_ROOT, ProfileError, ProfileStore
from ..tool_registry import ToolParameter, ToolSpec
from ..trusted_actions import allow_full_access
from ..vault import PasswordVault
from .vault_ui import VaultController

HABIT_REFRESH_MS = 30 * 60 * 1000
ROUTINE_CHECK_MS = 60 * 1000


class ProfileController(QObject):
    """Applies the active profile everywhere it matters: memory folder,
    permission gate, full access, audit, conversation language, Gmail login
    and the HUD (the persona reaches every AI request through
    settings.profile_provider); handles switching with the adult PIN, the
    profile editor, Settings changes, habits and routines."""

    language_changed = Signal(str)  # after a switch: app.py re-applies classic and Live voice at once
    _language_requested = Signal(str)  # from the voice tool's thread to the GUI thread

    def __init__(self, store: ProfileStore, *, window, settings_page, router, executor, audit, settings,
                 stt: Any = None, assistant: Any = None, learner: HabitLearner | None = None,
                 vault: PasswordVault | None = None, live_call_active=lambda: False, pause_listening=None,
                 resume_listening=None, live_audio=None) -> None:
        super().__init__(window)
        self.store = store
        self.window, self.settings_page, self.router, self.executor = window, settings_page, router, executor
        self.audit, self.settings, self.stt, self.assistant = audit, settings, stt, assistant
        self.learner = learner or HabitLearner(store.profile_dir, primary_id=store.primary_id)
        self._profile: dict = {}
        self._dialog = None
        self._memory_defaults = (router.conversation_memory.path, router.long_term_memory.path,
                                 router.episodic_memory.path, router.episodic_memory.state_path)
        self.gate = LevelGate(lambda: self.level)
        router.tools.level_gate = self.gate
        # Live voice (RealtimeVoiceConfig.from_settings) and every text AI
        # request (JarvisSettings.response_language_instruction) ask the app's
        # own settings object for the active profile.
        settings.profile_provider = store.active

        # Passwords (vault.py): one vault per profile, adults only.
        self.vault = VaultController(vault or PasswordVault(profile_id=store.active_id), window, router,
                                     live_call_active=live_call_active, pause_listening=pause_listening,
                                     resume_listening=resume_listening, live_audio=live_audio)
        window.profile_switch_requested.connect(self.switch)
        window.profile_editor_requested.connect(self.edit)
        settings_page.profile_changes_requested.connect(self.save_changes)
        window.habit_accepted.connect(self._accept_habit)
        window.habit_snoozed.connect(self._snooze_habit)
        window.habit_dismissed.connect(self._dismiss_habit)
        window.routine_run_requested.connect(self.run_routine)
        window.language_change_requested.connect(self.set_language)
        self._language_requested.connect(self.set_language)
        executor.result_ready.connect(self._on_result)
        if router.tools.get("set_conversation_language") is None:
            router.tools.register(ToolSpec(
                "set_conversation_language",
                "Switch the language Jarvis speaks and understands, right away and without a restart: en (English), "
                "bg (Bulgarian) or auto (follow the user's language). Use when the user asks to speak another language.",
                category="settings", parameters=(ToolParameter("language", "string", "en, bg or auto"),)),
                self._switch_language_tool)

        self._habit_timer = QTimer(self)
        self._habit_timer.setInterval(HABIT_REFRESH_MS)
        self._habit_timer.timeout.connect(self.refresh_habits)
        self._routine_timer = QTimer(self)
        self._routine_timer.setInterval(ROUTINE_CHECK_MS)
        self._routine_timer.timeout.connect(self.check_routines)
        self.apply()
        self._habit_timer.start()
        self._routine_timer.start()

    @property
    def level(self) -> str:
        return normalize_level(self._profile.get("permission_level"))

    # ---------------------------------------------------------- applying

    def apply(self) -> None:
        profile = self.store.active()
        self._profile = profile
        profile_id, level = profile["id"], self.level
        folder = self.store.memory_dir(profile_id)
        if level == "guest":  # a guest starts clean every time and nothing stays behind
            folder = self.store.profile_dir(profile_id) / "memory"
            shutil.rmtree(folder, ignore_errors=True)
        self._point_memory(folder)
        allow_full_access(full_access_allowed(level))
        self.audit.profile_id = profile_id
        self.vault.set_profile(profile_id)
        credentials = getattr(getattr(getattr(self.router, "gmail", None), "auth", None), "store", None)
        if isinstance(credentials, GmailCredentialStore):  # each adult connects their own Gmail
            credentials.target = GMAIL_TARGET if self.store.is_primary(profile_id) else f"{GMAIL_TARGET}/{profile_id}"
        language = profile.get("language")
        if language:  # the conversation language is the active profile's
            self.settings.openai["conversation_language"] = language
            self.window.set_language(language)
        for component in (self.stt, self.assistant):
            setter = getattr(component, "set_conversation_language", None)
            if callable(setter) and language:
                setter(language)
        self.window.set_profiles(self.store.list_profiles(), self.store.avatar_paths())
        self.window.set_profile(profile, self.store.avatar_path(profile_id))
        self.learner.profile_id = profile_id
        self.refresh_habits()

    def _point_memory(self, folder: Path | None) -> None:
        conversation, long_term, episodic = (self.router.conversation_memory, self.router.long_term_memory,
                                             self.router.episodic_memory)
        if folder is None:
            conversation.path, long_term.path, episodic.path, episodic.state_path = self._memory_defaults
        else:
            conversation.path = folder / "conversation_history.jsonl"
            long_term.path = folder / "memory.sqlite3"
            episodic.path = folder / "episodic_memory.jsonl"
            episodic.state_path = folder / "episodic_memory_state.json"
        long_term._schema_ready = False  # the new file may not have its table yet

    # ----------------------------------------------------------- actions

    def switch(self, profile_id: str, pin: str | None = None):
        result = self.store.switch(profile_id, pin=pin)
        while not result.ok and result.metadata.get("pin_required") and not result.metadata.get("locked"):
            target = self.store.get(profile_id) or {}
            pin = self.window.ask_adult_pin(target.get("display_name", ""),
                                            error=result.message if pin is not None else "")
            if pin is None:
                return result
            result = self.store.switch(profile_id, pin=pin)
        if result.ok:
            self.apply()
        self.window.show_feedback(result.message, error=not result.ok)
        return result

    def edit(self, profile_id: str):
        profile = self.store.get(profile_id) if profile_id else None
        if profile_id and profile is None:
            return None
        dialog = self.window.open_profile_editor(
            profile, self.store.avatar_path(profile_id) if profile else None, pin_set=self.store.has_pin())
        target = {"id": profile_id, "failed": False}

        def saved(changes: dict) -> None:
            try:
                if target["id"]:
                    self.store.update(target["id"], changes)
                else:
                    changes = dict(changes)
                    target["id"] = self.store.create(changes.pop("display_name"), **changes)["id"]
            except ProfileError as error:
                target["failed"] = True
                self.window.show_feedback(str(error), error=True)

        def avatar(png: bytes) -> None:
            if target["id"] and not target["failed"]:
                self._guard(lambda: self.store.set_avatar(target["id"], png))

        dialog.saved.connect(saved)
        dialog.avatar_chosen.connect(avatar)
        dialog.adult_pin_chosen.connect(lambda pin: self._guard(lambda: self.store.set_pin(pin)))
        dialog.delete_requested.connect(lambda deleted: self._guard(lambda: self.store.delete(deleted)))
        dialog.finished.connect(lambda _code: self.apply())
        self._dialog = dialog
        return dialog

    def save_changes(self, profile_id: str, changes: dict) -> None:
        if self._guard(lambda: self.store.update(profile_id, changes)):
            self.apply()

    def set_language(self, code: str) -> None:
        """Switch the conversation language at once: the profile, classic voice,
        Settings, the HUD and (through language_changed) a running Live call."""
        if code not in ("en", "bg", "auto"):
            return
        profile = self.store.active()
        if profile.get("language") != code and not self._guard(
                lambda: self.store.update(profile["id"], {"language": code})):
            return
        self.apply()
        self.language_changed.emit(code)

    def _switch_language_tool(self, language: str) -> CommandResult:
        spoken = {"english": "en", "английски": "en", "bulgarian": "bg", "български": "bg", "автоматично": "auto"}
        code = spoken.get(language.strip().lower(), language.strip().lower())
        if code not in ("en", "bg", "auto"):
            return CommandResult(False, "Use en, bg or auto.", metadata={"executed": False})
        self._language_requested.emit(code)
        message = {"en": "Switched to English.", "bg": "Минавам на български.",
                   "auto": "I will follow the language you speak."}[code]
        return CommandResult(True, message, metadata={"conversation_language": code})

    def _guard(self, change) -> bool:
        try:
            change()
        except ProfileError as error:
            self.window.show_feedback(str(error), error=True)
            return False
        return True

    def _on_result(self, _source: str, _text: str, result) -> None:
        metadata = getattr(result, "metadata", None) or {}
        if metadata.get("blocked_by_level"):
            self.window.show_permission_block(result.message, metadata["blocked_by_level"])
        # "наричай ме …" names the active profile once profiles exist.
        if result.ok and metadata.get("preference_key") == "address_name":
            personality = dict(self._profile.get("personality") or {})
            personality["address_as"] = str(metadata.get("preference_value") or "").strip()
            if self._guard(lambda: self.store.update(self._profile["id"], {"personality": personality})):
                self.apply()

    # ------------------------------------------------------------ habits

    def refresh_habits(self) -> None:
        try:
            suggestions = self.learner.suggestions(self._profile)
        except (OSError, ValueError):
            suggestions = []
        self.window.show_habit_suggestions(suggestions)

    def _accept_habit(self, habit_id: str) -> None:
        routine = self.learner.accept(habit_id)
        if routine is not None:
            self.window.show_feedback(f"Routine saved for {routine['trigger']['time']}. "
                                      "Jarvis will ask before running it.")

    def _snooze_habit(self, habit_id: str) -> None:
        self.learner.snooze(habit_id)

    def _dismiss_habit(self, habit_id: str) -> None:
        self.learner.dismiss(habit_id)

    def check_routines(self) -> None:
        if self.level == "guest":
            return
        for routine in self.learner.due_routines():
            self.learner.mark_offered(routine["id"])
            self.window.show_routine_due(routine)

    def run_routine(self, routine_id: str) -> None:
        routine = next((item for item in self.learner.routines() if item.get("id") == routine_id), None)
        if routine is None:
            return
        for action in routine.get("actions", []):
            if action.get("command"):
                self.executor.submit(str(action["command"]), "routine")
            elif action.get("tool"):
                self.executor.submit_tool(str(action["tool"]), dict(action.get("arguments") or {}), source="routine")


def wire_profiles(*, window, settings_page, router, executor, audit, settings, stt: Any = None,
                  assistant: Any = None, root: Path | str = PROFILES_ROOT, **voice) -> ProfileController:
    """The one call app.py makes (after the settings page and tray exist).
    `voice` passes live_call_active / pause_listening / resume_listening /
    live_audio (the RealtimeVoiceWorker) to the vault."""
    store = ProfileStore(root, settings=settings)
    return ProfileController(store, window=window, settings_page=settings_page, router=router, executor=executor,
                             audit=audit, settings=settings, stt=stt, assistant=assistant, **voice)
