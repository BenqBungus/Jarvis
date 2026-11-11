"""Role packs: bundles of guidance and quick actions for what a person does.

Owned by Claude (docs/claude/PERSONALIZATION_HANDOFF.md, C2). A pack adds
Live-voice/chat guidance and HUD quick actions; it grants no new permissions.
Tool names in the guidance must exist in the tool registry
(tests/test_role_packs.py checks this).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QuickAction:
    label: str
    command: str = ""  # sent like a typed command
    signal: str = ""  # or the name of a MainWindow signal to emit


@dataclass(frozen=True)
class RolePack:
    id: str
    name: str
    glyph: str
    tagline: str
    instructions: str
    quick_actions: tuple[QuickAction, ...]


PACKS: dict[str, RolePack] = {pack.id: pack for pack in (
    RolePack(
        "gamer", "Gamer", "game", "Game coach, performance checks and Gaming mode.",
        "Gaming: when the user asks about a game, strategy, builds, settings or performance, act as an expert coach. "
        "Give specific, actionable advice for that exact game (roles, builds, positioning, economy, settings), not "
        "generic tips. If the game is unclear, ask briefly or check list_processes. With approved screen sharing, "
        "base in-game advice on the newest frame; without it, never claim to see the game. For current patches, "
        "metas or tier lists use research_web and name sources. For stutter, low FPS or heat, check "
        "system_hardware_status, system_temperatures and top_processes, then suggest concrete fixes such as closing "
        "background apps, game_mode or a driver check with nvidia_driver_info.",
        (QuickAction("Gaming mode", command="режим игра"),
         QuickAction("Temperatures", command="провери температурите"),
         QuickAction("What's slowing me", command="какво ми товари компютъра"))),
    RolePack(
        "student", "Student", "books", "Teaches instead of just answering; focus timer and study mode.",
        "Studying: when the user studies or asks for homework help, teach rather than only answer: explain step "
        "by step, give a small example and check understanding with one short question. For facts and research "
        "use research_web and cite sources. When the user wants to focus, offer study mode with apply_mode and "
        "short focus sessions with breaks.",
        (QuickAction("Study mode", command="режим учене"),
         QuickAction("Quiet mode", command="quiet mode"))),
    RolePack(
        "creator", "Creator", "headphones", "Recording-ready: quiet PC, audio check, fewer distractions.",
        "Creating: before recording or streaming, help the user get ready: suggest quiet mode with apply_mode, "
        "check audio with voice_diagnostics, list what is running with top_processes, and close distracting apps "
        "only with close_app after confirmation. Keep checklists short.",
        (QuickAction("Quiet mode", command="quiet mode"),
         QuickAction("Voice check", signal="voice_diagnostics_requested"),
         QuickAction("What's running", command="какво ми товари компютъра"))),
    RolePack(
        "developer", "Developer", "monitor", "Precise code help, reviewed file edits and Screen Chat.",
        "Coding: for code questions give precise answers with code. For changes to a file use propose_file_edit "
        "and show the diff before saving. For an error on screen use ask_shared_screen during approved screen "
        "sharing, or suggest Screen Chat for a project-aware look.",
        (QuickAction("Screen Chat", signal="screen_chat_requested"),
         QuickAction("Recent file", command="отвори последния файл"))),
    RolePack(
        "business", "Business", "mail", "Inbox triage, deadlines and professional drafts.",
        "Business: for email use gmail_search, gmail_read, gmail_summarize and gmail_advise. Lead with deadlines, "
        "requests and the next step. Draft replies as text for the user to send; never send anything yourself.",
        (QuickAction("Unread email", command="непрочетени имейли"),
         QuickAction("Check email", command="провери пощата"))),
)}
# Applied when a person has never chosen packs, so the gaming coach keeps
# working for everyone who had it before packs existed.
DEFAULT_PACKS: tuple[str, ...] = ("gamer",)


def normalize_packs(value: Any) -> list[str]:
    """Known pack ids in PACKS order; DEFAULT_PACKS when nothing was ever chosen."""
    if value is None:
        return list(DEFAULT_PACKS)
    if not isinstance(value, (list, tuple)):
        return []
    chosen = {item for item in value if isinstance(item, str)}
    return [pack_id for pack_id in PACKS if pack_id in chosen]


def pack_instructions(pack_ids: Any) -> str:
    return " ".join(PACKS[pack_id].instructions for pack_id in normalize_packs(pack_ids))
