from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from pathlib import Path

from .audit import AuditLogger
from .ai_client import JarvisAI
from .browser import BrowserController, PageReader, WebResearcher
from .config import APP_ALIASES, WAKE_WORDS, WEBSITES
from .error_taxonomy import enrich_error_metadata
from .files import FileSearchService
from .documents import DocumentService
from .driver_updates import DriverUpdates
from .gmail import GmailService, register_gmail_tools
from .file_editing import FileEditing
from .vision.sharing import ScreenSharing
from .local_commands import LocalCommandService, TeachingService
from .intent_parser import ParsedIntent
from .models import CommandResult
from .memory import ConversationMemory, EpisodicMemory, LongTermMemory, SemanticMemorySearch
from .permissions import ADMIN, BLOCKED, CONFIRM, SAFE, IntentMetadata, confirmed_from_result
from .privacy import redact_sensitive_text, contains_private_content
from .safety import SafetyPolicy
from .shopping import deal_candidates, find_site, site_search_candidate
from .tool_registry import ToolCall, ToolParameter, ToolRegistry, ToolSpec, build_core_tool_registry, validate_tool_arguments
from .user_settings import SETTINGS_PATH, JarvisSettings
from .vision import ScreenCapture, ScreenVision
from .web_context import WebContext
from .windows_actions import WindowsActions
from .workflows import WorkflowPlan, WorkflowPlanPreview, WorkflowRunner, WorkflowStep, preview_workflow_plan


WORKFLOW_RETRYABLE_TOOLS = frozenset(
    {
        "answer_with_web_search",
        "extract_webpage",
        "research_web",
        "browser_search",
        "browser_inspect",
        "browser_tabs",
        "browser_open_search_page",
        "save_deal_candidates",
    }
)


@dataclass(frozen=True)
class PendingClarification:
    parsed: ParsedIntent
    tool_call: ToolCall
    question: str
    fill_argument: str = ""
    fill_type: str = "string"


class CommandRouter:
    def __init__(
        self,
        actions: WindowsActions,
        safety: SafetyPolicy,
        ai: JarvisAI | None = None,
        settings: JarvisSettings | None = None,
        settings_path: Path = SETTINGS_PATH,
    ) -> None:
        self.actions = actions
        self.safety = safety
        self.ai = ai
        self.settings = settings or JarvisSettings()
        if isinstance(self.safety, SafetyPolicy):
            self.safety.settings = self.settings
        self.settings_path = settings_path
        if getattr(self.actions, "settings", None) is None:
            self.actions.settings = self.settings
        self.conversation_memory = ConversationMemory()
        self.long_term_memory = LongTermMemory()
        self.episodic_memory = EpisodicMemory()
        self.semantic_memory = SemanticMemorySearch(
            long_term_memory=self.long_term_memory,
            episodic_memory=self.episodic_memory,
        )
        self.audit_reader = AuditLogger()
        self.web_context = WebContext()
        self.page_reader = PageReader()
        self.browser = BrowserController(actions=actions, web_context=self.web_context)
        self.researcher = WebResearcher(page_reader=self.page_reader, web_context=self.web_context, ai=ai)
        self.screen_vision = ScreenVision(
            capture=ScreenCapture(dry_run=getattr(actions, "dry_run", False)),
            ai=ai,
            dry_run=getattr(actions, "dry_run", False),
        )
        self.tools: ToolRegistry = build_core_tool_registry(
            actions,
            ai,
            memory=self.long_term_memory,
            conversation_memory=self.conversation_memory,
            episodic_memory=self.episodic_memory,
            semantic_memory=self.semantic_memory,
            audit=self.audit_reader,
            web_context=self.web_context,
            page_reader=self.page_reader,
            researcher=self.researcher,
            browser=self.browser,
            screen_vision=self.screen_vision,
            settings=self.settings,
            settings_path=self.settings_path,
        )
        self.workflow_runner = WorkflowRunner(self.tools)
        self.gmail = GmailService(ai, dry_run=getattr(actions, "dry_run", False),
                                  cancelled=self.workflow_runner.cancelled.is_set)
        register_gmail_tools(self.tools, self.gmail)
        self.actions.local_files.cancelled = self.workflow_runner.cancelled.is_set
        self.tools.register(ToolSpec("run_autonomous_task",
            "Work on a user-requested multi-step goal, observing results before choosing each next step. "
            "Limited to 8 decisions and 180 seconds between operations. Risky steps still need user confirmation.",
            category="agent", parameters=(ToolParameter("goal", "string", "The user's explicit goal."),)),
            lambda goal: self._run_adaptive_ai_workflow(goal) or CommandResult(False, "AI planning is unavailable."))
        self.tools.register(ToolSpec("cancel_task", "Request cancellation of the current task; do not undo completed actions.",
                                     category="agent"), self.cancel_task)
        self.files = FileSearchService(dry_run=getattr(actions, "dry_run", False), cancelled=self.workflow_runner.cancelled.is_set)
        self.screen_sharing = ScreenSharing(ai, dry_run=getattr(actions, "dry_run", False), cancelled=self.workflow_runner.cancelled.is_set)
        self.file_editing = FileEditing(self.files, actions.local_files, ai,
                                       dry_run=getattr(actions, "dry_run", False), cancelled=self.workflow_runner.cancelled.is_set)
        self.tools.register(ToolSpec("start_screen_sharing", "Share the primary screen until Stop. During Realtime voice, changed frames are automatically sent to OpenAI about every two seconds, increasing API usage. "
            "Screenshots may expose private information. Requires confirmation and a visible GUI Stop indicator. Not full-frame-rate video.",
            permission=CONFIRM, requires_confirmation=True, category="vision"), self.screen_sharing.start)
        self.tools.register(ToolSpec("stop_screen_sharing", "Stop screen snapshots immediately. Already-sent requests cannot be recalled.", category="vision"), self.screen_sharing.stop)
        self.tools.register(ToolSpec("screen_sharing_status", "Report sharing status without taking a screenshot.", category="vision"), self.screen_sharing.status)
        self.tools.register(ToolSpec("ask_shared_screen", "Capture a fresh primary-screen snapshot during an approved sharing session and ask OpenAI about visible code, errors or writing. "
            "No files are edited, no buttons clicked, no direct Microsoft Copilot connection. Ask for the actual file path before proposing edits.",
            category="vision", parameters=(ToolParameter("question", "string", "Question about what is currently visible."),)), self.screen_sharing.ask)
        self.tools.register(ToolSpec("propose_file_edit", "Read an explicitly chosen UTF-8 text/code file (up to 64000 bytes), send it to OpenAI and show a proposed diff. "
            "Requires confirmation for cloud disclosure. No file changed. Not PDF/DOCX. Do not infer full file contents from screenshots.",
            permission=CONFIRM, requires_confirmation=True, category="files", parameters=(
                ToolParameter("path", "string", "Exact user-selected local file path."),
                ToolParameter("instructions", "string", "Requested wording or code change, preserving unrelated content."))), self.file_editing.propose)
        self.tools.register(ToolSpec("preview_file_edit", "Show the current proposed diff without saving. Proposal expires after five minutes.", category="files"), self.file_editing.preview)
        self.tools.register(ToolSpec("save_file_edit", "After the user reviews the proposed diff, save it to their chosen NEW local filename. "
            "Requires confirmation; original unchanged, no overwrite, same extension, no code execution. Use exact observed proposal_id.",
            permission=CONFIRM, requires_confirmation=True, category="files", parameters=(
                ToolParameter("proposal_id", "string", "Exact ID returned by the preview."),
                ToolParameter("destination", "string", "Explicit existing local folder and new filename; same extension."))), self.file_editing.save_copy)
        self.tools.register(ToolSpec("discard_file_edit", "Discard the current edit proposal; no file changes.", category="files"), self.file_editing.discard)
        # Reviewed driver installs (Claude, by the user's decision of 2026-09-24; see driver_updates.py).
        self.driver_updates = DriverUpdates(dry_run=getattr(actions, "dry_run", False),
                                            cancelled=self.workflow_runner.cancelled.is_set)
        for spec, handler in self.driver_updates.tool_specs():
            self.tools.register(spec, handler)
        self.documents = DocumentService(self.files, actions.local_files, ai,
                                         cancelled=self.workflow_runner.cancelled.is_set, dry_run=getattr(actions, "dry_run", False))
        self.tools.register(ToolSpec("analyze_document",
            "Read an explicitly chosen local PDF/DOCX and send extracted text to OpenAI for summary and critical assessment. "
            "Requires confirmation for cloud disclosure. Ask for an exact file if only a folder is given; never guess. "
            "Returns document_id for later questions/writing. Text only: no OCR/image interpretation, coverage limits apply. Does not launch Word or a PDF viewer.",
            permission=CONFIRM, requires_confirmation=True, category="documents", parameters=(
                ToolParameter("path", "string", "User-selected absolute file path or Downloads/Documents path ending in .pdf or .docx."),
                ToolParameter("question", "string", "What to summarize or critically assess; optional default summary.", required=False))), self.documents.analyze)
        self.tools.register(ToolSpec("document_context", "Identify the active document and its coverage/id without returning its text. Use before document follow-ups; context expires after 30 minutes.",
                                    category="documents"), self.documents.context)
        self.tools.register(ToolSpec("ask_document", "Answer a follow-up about the already approved active document using OpenAI. "
            "Use its observed document_id, never guess; retains four recent document exchanges. Do not answer source-specific questions from general memory instead.",
            category="documents", parameters=(ToolParameter("document_id", "string", "Exact observed active document_id."),
                                               ToolParameter("question", "string", "User's question or request for critical opinion."))), self.documents.ask)
        self.tools.register(ToolSpec("draft_document", "Use OpenAI to write a source-based Word draft/chapter from the approved active document and discussion. "
            "Confirm before generating and saving. Ask for topic/title, length and exact destination .docx path if unclear. "
            "New file only, existing parent folder, no overwrite. 300-4000 words per draft/chapter; not a complete verified thesis or automatic submission. "
            "Use observed document_id. Never claim saving succeeded without a successful result.",
            permission=CONFIRM, requires_confirmation=True, category="documents", parameters=(
                ToolParameter("document_id", "string", "Observed document context ID."),
                ToolParameter("destination", "string", "User-chosen existing local folder plus new .docx filename."),
                ToolParameter("title", "string", "Specific subject and purpose of the draft."),
                ToolParameter("instructions", "string", "Requested argument, structure and academic requirements."),
                ToolParameter("target_words", "integer", "Approximate target between 300 and 4000 words, not guaranteed exact.", required=False))), self.documents.draft)
        self.tools.register(ToolSpec("forget_document", "Clear active document text and discussion from this process. Does not delete saved drafts, audit/chat history or provider records.",
                                    category="documents"), self.documents.forget)
        self.teaching = TeachingService()
        self.local_commands = LocalCommandService(actions, self.settings, self.files, self.tools, safety)
        self.tools.register(ToolSpec("search_local_files", "Find local files/folders by name, extension, modification date or file size. Contents are NOT read unless content is explicitly supplied. "
            "For a user-requested content search, ask which folder to inspect if not specified; never guess the scope. "
            "Content search is local literal text matching in TXT/MD/CSV only, excluding private/config files; no excerpts are returned. "
            "Fuzzy mode suggests approximate names, never auto-opens. All filters are combined. "
            "Defaults to Desktop, Documents, Downloads and Pictures, NOT every drive; reports partial searches. "
            "Inspect multiple results and ask which to open. Use open_file_result with the observed ordinal and search_id, never guess them. Empty query requires another filter.",
            category="files", parameters=(ToolParameter("query", "string", "Filename fragment, or omit for filter-only search.", required=False),
            ToolParameter("root", "string", "Absolute local folder or Desktop/Documents/Downloads/Pictures, optionally with a subfolder.", required=False),
            ToolParameter("extension", "string", "One file extension, e.g. pdf or docx; no wildcards.", required=False),
            ToolParameter("kind", "string", "any, file or folder. Size and extension filters only apply to files.", required=False),
            ToolParameter("modified_after", "string", "Inclusive local modification date YYYY-MM-DD; not creation date.", required=False),
            ToolParameter("modified_before", "string", "Inclusive local modification date YYYY-MM-DD.", required=False),
            ToolParameter("min_size_bytes", "integer", "Inclusive minimum file size in bytes, not folder totals.", required=False),
            ToolParameter("max_size_bytes", "integer", "Inclusive maximum file size in bytes.", required=False),
            ToolParameter("content", "string", "Only for explicit content-search requests: literal phrase inside TXT/MD/CSV. Requires a user-chosen root. No PDF/DOCX parsing.", required=False),
            ToolParameter("match_mode", "string", "contains (default), exact (full name including extension), or fuzzy (approximate name).", required=False))), self.files.search)
        self.tools.register(ToolSpec("show_file_results", "Show the latest numbered local file results without rescanning or opening anything. Selections expire after five minutes.",
                                    category="files"), self.files.show_results)
        self.tools.register(ToolSpec("open_file_result", "Open one explicitly chosen local file/folder result after rechecking its identity and type. Use the exact ordinal and search_id returned by search_local_files/show_file_results. Not a web result. Ask for clarification when the result type or selection is ambiguous. Do not fall back to a different path after rejection.",
            category="files", parameters=(ToolParameter("ordinal", "integer", "One-based observed file result number."),
            ToolParameter("search_id", "string", "Exact search_id from the displayed file results."))), self.files.open_result)
        self.tools.register(ToolSpec("open_local_path", "Open an explicitly requested local folder or common document. "
            "Scripts, executables, shortcuts, junctions and network paths are rejected. An accepted launch is not proof of a visible window.",
            category="files", parameters=(ToolParameter("path", "string", "Observed absolute path or Desktop/Documents/Downloads/Pictures."),)), self.files.open_path)
        self.tools.register(ToolSpec("teach_task", "Teach the user steps without executing any action or inspecting the screen. "
            "Local guides cover volume, files, updates and NitroSense. Use when asked to teach, not perform.",
            category="learning", parameters=(ToolParameter("topic", "string", "What the user wants to learn."),)), self.teaching.explain)
        self._pending_clarification: PendingClarification | None = None

    def cancel_task(self) -> CommandResult:
        self.workflow_runner.cancelled.set()
        return CommandResult(True, "Stop requested. Completed actions are not undone.", metadata={"cancel_requested": True})

    def handle(self, raw_text: str) -> CommandResult:
        text = self._normalize(raw_text)
        classification = self._classify(text)
        tried_conversation_first_intent = False

        if not text:
            return self._finalize(
                CommandResult(False, "I did not catch a command."),
                classification,
            )
        # Kid and Guest profiles (permission_levels.py): rule-based commands
        # are checked here, tools in ToolRegistry.execute.
        check_intent = getattr(self.tools.level_gate, "check_intent", None)
        level_blocked = check_intent(classification) if callable(check_intent) else None
        if level_blocked is not None:
            return self._finalize(level_blocked, classification)

        teaching = re.match(r"^(?:научи ме|teach me)\b\s*(.*)$", text, re.I)
        if teaching:
            return self.teaching.explain(teaching[1])
        local = re.match(r"^(?:локално|local)\s*[: ]\s*(.+)$", raw_text.strip(), re.I)
        if local:
            return self.local_commands.handle(local[1])

        pending_result = self._handle_pending_clarification(text)
        if pending_result is not None:
            return pending_result

        if classification.permission == BLOCKED:
            return self._finalize(
                CommandResult(
                    False,
                    "That command is blocked. Kernel-level or security-sensitive actions need a separate approved design.",
                ),
                classification,
            )

        original = raw_text.strip()
        for wake_word in WAKE_WORDS:
            if original.lower().startswith(wake_word):
                original = original[len(wake_word):].lstrip(" ,;:")
                break
        from .gmail_commands import gmail_command
        gmail_result = gmail_command(original, self.local_commands._execute)
        if gmail_result is not None:
            return gmail_result
        resource_result = self.local_commands.resource_command(original)
        if resource_result is not None:
            return resource_result
        adaptive_goal = self._extract_adaptive_workflow_goal(original)
        if adaptive_goal:
            result = self._run_adaptive_ai_workflow(adaptive_goal)
            if result is not None:
                return result

        managed_match = re.match(r"^(?:managed browser|управляван браузър)\s+(.+)$", text, re.I)
        managed_reads = {"browser tabs": "tabs", "табове на браузъра": "tabs",
                         "inspect browser": "inspect", "прочети текущата страница": "inspect"}
        if managed_match:
            # Preserve URL path/query case from the original command.
            raw_url = re.split(r"managed browser\s+|управляван браузър\s+", raw_text, maxsplit=1, flags=re.I)[-1].strip()
            return self._finalize(self.tools.execute(ToolCall("browser_navigate", {"url": raw_url})), classification)
        if text in managed_reads:
            return self._finalize(self.tools.execute(ToolCall(f"browser_{managed_reads[text]}")), classification)

        if self._contains_any(text, "list tools", "show tools", "available tools", "покажи tools", "покажи инструмент", "какви инструменти"):
            return self._finalize(
                CommandResult(True, self.tools.describe(), metadata={"tools": [spec.name for spec in self.tools.list_specs()]}),
                classification,
            )

        if self._is_voice_diagnostics_request(text):
            return self._finalize(self.tools.execute(ToolCall("voice_diagnostics")), classification)

        preference_set = self._extract_user_preference_set(text)
        if preference_set is not None:
            key, value = preference_set
            return self._finalize(self._set_user_preference(key, value), classification)

        if self._is_user_preferences_request(text):
            return self._finalize(self._show_user_preferences(), classification)

        if not self._should_keep_local_rule_before_ai(text, classification):
            tried_conversation_first_intent = True
            parsed_intent = self._parse_ai_intent(text)
            if parsed_intent is not None:
                return self._handle_parsed_intent(text, parsed_intent)

        open_first_deal_query = self._extract_open_first_deal_workflow(text)
        if open_first_deal_query is not None:
            return self._finalize(self._run_open_first_deal_workflow(open_first_deal_query), classification)

        action_episode_minutes = self._extract_action_episode_minutes(text)
        if action_episode_minutes is not None:
            return self._finalize(self._summarize_action_episode(action_episode_minutes), classification)

        action_minutes = self._extract_action_history_minutes(text)
        if action_minutes is not None:
            return self._finalize(self._show_action_history(action_minutes), classification)

        trace_filter = self._extract_trace_filter(text)
        if trace_filter is not None:
            return self._finalize(self._show_filtered_traces(**trace_filter), classification)

        if self._is_trace_request(text):
            return self._finalize(self._show_latest_trace(), classification)

        search_and_open = self._extract_browser_search_and_open(text)
        if search_and_open is not None:
            query, ordinal = search_and_open
            return self._finalize(self.browser.search_and_open(query, ordinal=ordinal), classification)

        read_ordinal = self._extract_read_ordinal(text)
        if read_ordinal is not None:
            return self._finalize(self._read_saved_candidate(read_ordinal), classification)

        read_match = self._extract_read_matching_query(text)
        if read_match is not None:
            return self._finalize(self._read_matching_saved_candidate(read_match), classification)

        read_url = self._extract_read_url(text)
        if read_url:
            return self._finalize(self._read_url_and_record(read_url), classification)

        if self._is_browser_session_request(text):
            return self._finalize(self._show_browser_session(), classification)

        if self._is_browser_session_compare_request(text):
            return self._finalize(self._compare_browser_session_pages(), classification)

        browser_session_question = self._extract_browser_session_question(text)
        if browser_session_question is not None:
            return self._finalize(self._answer_browser_session_question(browser_session_question), classification)

        categorized_memory = self._extract_categorized_remember(text)
        if categorized_memory:
            content, category, importance = categorized_memory
            return self._finalize(self._remember_fact(content, category=category, importance=importance), classification)

        memory_update = self._extract_memory_update(text)
        if memory_update:
            memory_id, content = memory_update
            return self._finalize(self._update_memory(memory_id, content=content), classification)

        category_update = self._extract_memory_category_update(text)
        if category_update:
            memory_id, category = category_update
            return self._finalize(self._update_memory(memory_id, category=category), classification)

        if self._is_memory_categories_request(text):
            return self._finalize(self._list_memory_categories(), classification)

        remember_text = self._extract_remember_text(text)
        if remember_text:
            return self._finalize(self._remember_fact(remember_text), classification)

        forget_query = self._extract_forget_query(text)
        if forget_query:
            return self._finalize(self._forget_memory(forget_query), classification)

        if self._is_episode_summary_request(text):
            return self._finalize(self._summarize_conversation_episode(), classification)

        semantic_memory_query = self._extract_semantic_memory_query(text)
        if semantic_memory_query is not None:
            return self._finalize(self.semantic_memory.format_search(semantic_memory_query), classification)

        episode_query = self._extract_episode_memory_query(text)
        if episode_query is not None:
            return self._finalize(self.episodic_memory.format_recent(query=episode_query), classification)

        memory_query = self._extract_memory_query(text)
        if memory_query is not None:
            return self._finalize(self._show_memory(memory_query), classification)

        ordinal = self._extract_open_ordinal(text)
        if ordinal is not None:
            return self._finalize(self._open_saved_candidate(ordinal), classification)

        open_match = self._extract_open_matching_query(text)
        if open_match is not None:
            return self._finalize(self.browser.open_matching_result(open_match), classification)

        deals_query = self._extract_deals_query(text)
        if deals_query is not None:
            return self._finalize(self._show_deal_candidates(deals_query), classification)

        research_query = self._extract_research_query(text)
        if research_query is not None:
            result = self.researcher.research(research_query)
            self._remember_conversation(text, result)
            return self._finalize(result, classification)

        browser_search_query = self._extract_browser_search_query(text)
        if browser_search_query is not None:
            return self._finalize(self.browser.search(browser_search_query), classification)

        if self._is_browser_automation_status_request(text):
            return self._finalize(self.browser.automation_status(), classification)

        if self._is_screen_vision_status_request(text):
            return self._finalize(self.screen_vision.status(), classification)

        screen_prompt = self._extract_screen_vision_prompt(text)
        if screen_prompt is not None:
            if not self.safety.confirm(
                "Analyze current screen",
                "Jarvis will capture the current screen and may send it to the configured AI vision model.",
            ):
                return self._finalize(CommandResult(False, "Screen vision cancelled."), classification)
            return self._finalize(self.screen_vision.describe(screen_prompt), classification)

        open_target = self._extract_open_target(text)
        if open_target:
            opened = self._open(open_target)  # the target lets habits.py learn what is opened
            return self._finalize(opened.with_metadata(metadata={**opened.metadata, "open_target": open_target}),
                                  classification)

        volume_percent = self._extract_volume_percent(text)
        if volume_percent is not None:
            return self._finalize(self.actions.set_volume(volume_percent), classification)

        if self._is_apply_preferred_volume_request(text):
            return self._finalize(self._apply_preferred_volume(), classification)

        if self._contains_any(text, "volume up", "increase volume", "увеличи звука", "усили звука"):
            return self._finalize(self.actions.volume_up(), classification)

        if self._contains_any(text, "volume down", "decrease volume", "намали звука"):
            return self._finalize(self.actions.volume_down(), classification)

        if self._contains_any(text, "mute", "заглуши", "спри звука"):
            return self._finalize(self.actions.toggle_mute(), classification)

        if self._contains_any(text, "undo", "rollback", "върни последното", "отмени последното"):
            if not self.safety.confirm("Undo last reversible action", "This may restore a file/folder path, volume, power mode, network, or Bluetooth state."):
                return self._finalize(CommandResult(False, "Undo cancelled."), classification)
            return self._finalize(self.actions.undo_last_action(), classification)

        if self._contains_any(text, "refresh app database", "refresh apps", "обнови приложенията", "сканирай приложенията"):
            return self._finalize(self.actions.refresh_app_database(), classification)

        if self._contains_any(text, "list app database", "list apps", "покажи приложенията", "списък с приложения"):
            return self._finalize(self.actions.list_app_database(), classification)

        mode = self._extract_mode(text)
        if mode:
            if mode == "gaming" and self._contains_any(text, "режим игра", "game mode", "gaming mode"):
                if not self.safety.confirm(
                    "Gaming mode",
                    "This can close common background apps, switch power mode, open NitroSense, and check temperatures.",
                ):
                    return self._finalize(CommandResult(False, "Gaming mode cancelled."), classification)
                return self._finalize(self.actions.game_mode(), classification)
            return self._finalize(self.actions.apply_mode(mode), classification)

        if self._contains_any(text, "open last file", "open recent file", "отвори последния файл", "отвори последния документ"):
            return self._finalize(self.actions.open_recent_file(), classification)

        docx_topic = self._extract_docx_topic(text)
        if docx_topic:
            return self._finalize(self.actions.create_docx(docx_topic), classification)

        if self._contains_any(text, "clean temp", "clear temp", "почисти temp", "изчисти temp", "почисти временни"):
            if not self.safety.confirm(
                "Clean temp files",
                "This removes old files from the current user's Windows temp folder.",
            ):
                return self._finalize(CommandResult(False, "Temp cleanup cancelled."), classification)
            return self._finalize(self.actions.cleanup_temp_files(), classification)

        if self._contains_any(text, "what is loading", "top processes", "какво ми товари", "какво товари", "натоварва компютъра"):
            return self._finalize(self.actions.top_processes(), classification)

        if self._contains_any(text, "startup programs", "startup apps", "стартъп програм", "стартиращи програм"):
            return self._finalize(self.actions.startup_programs(), classification)

        temp_threshold = self._extract_temperature_threshold(text)
        if temp_threshold is not None:
            return self._finalize(self.actions.temperature_warning(temp_threshold), classification)

        if self._contains_any(text, "driver update", "driver updates", "ъпдейт на драйвер", "ъпдейти на драйвер", "драйвер ъпдейт"):
            return self._finalize(self.actions.check_driver_updates(), classification)

        if self._contains_any(text, "windows update", "ъпдейт", "update", "актуализации"):
            if self._contains_any(text, "open", "отвори", "settings", "настройки"):
                return self._finalize(self.actions.open_windows_update(), classification)
            return self._finalize(self.actions.check_windows_updates(), classification)

        if self._contains_any(text, "windows settings", "настройки на windows", "настройките"):
            return self._finalize(self.actions.open_windows_update(), classification)

        if self._contains_any(text, "nvidia", "нвидиа"):
            if self._contains_any(text, "open", "отвори", "download", "изтегли"):
                return self._finalize(self.actions.open_nvidia_driver_page(), classification)
            return self._finalize(self.actions.nvidia_driver_info(), classification)

        driver_category = self._extract_driver_category(text)
        if driver_category:
            return self._finalize(self.actions.driver_info(driver_category), classification)

        if self._contains_any(text, "temperature", "temperatures", "температура", "температури", "cpu temp", "gpu temp"):
            return self._finalize(self.actions.system_temperatures(), classification)

        if self._contains_any(text, "nitrosense", "nitro sense", "нитросенс", "нитро сенс"):
            if self._contains_any(text, "update", "ъпдейт", "updates", "актуализации"):
                return self._finalize(self.actions.open_acer_support(), classification)
            return self._finalize(self.actions.open_nitrosense(), classification)

        create_result = self._extract_create_target(text)
        if create_result:
            kind, target = create_result
            if kind == "folder":
                return self._finalize(self.actions.create_folder(target), classification)
            return self._finalize(self.actions.create_file(target), classification)

        if self._contains_any(text, "restart", "рестартирай"):
            if not self.safety.confirm("Restart laptop", "This will close apps and restart Windows."):
                return self._finalize(CommandResult(False, "Restart cancelled."), classification)
            return self._finalize(self.actions.restart(), classification)

        if self._contains_any(text, "shutdown", "изключи лаптопа", "изключи компютъра"):
            if not self.safety.confirm("Shutdown laptop", "This will close apps and power off Windows."):
                return self._finalize(CommandResult(False, "Shutdown cancelled."), classification)
            return self._finalize(self.actions.shutdown(), classification)

        if self._contains_any(text, "sleep", "приспи", "заспи"):
            if not self.safety.confirm("Put laptop to sleep", "This will suspend the current Windows session."):
                return self._finalize(CommandResult(False, "Sleep cancelled."), classification)
            return self._finalize(self.actions.sleep(), classification)

        if self._contains_any(text, "internet on", "enable internet", "пусни интернета", "включи интернета"):
            if not self.safety.confirm("Enable internet adapters", "This may require administrator rights."):
                return self._finalize(CommandResult(False, "Internet enable cancelled."), classification)
            return self._finalize(self.actions.enable_internet(), classification)

        if self._contains_any(text, "internet off", "disable internet", "спри интернета", "изключи интернета"):
            if not self.safety.confirm(
                "Disable internet adapters",
                "This will disconnect the laptop from the network and may require administrator rights.",
            ):
                return self._finalize(CommandResult(False, "Internet disable cancelled."), classification)
            return self._finalize(self.actions.disable_internet(), classification)

        if self._contains_any(text, "bluetooth on", "enable bluetooth", "пусни bluetooth", "пусни блутут", "включи bluetooth", "включи блутут"):
            if not self.safety.confirm("Enable Bluetooth devices", "This may require administrator rights."):
                return self._finalize(CommandResult(False, "Bluetooth enable cancelled."), classification)
            return self._finalize(self.actions.enable_bluetooth(), classification)

        if self._contains_any(text, "bluetooth off", "disable bluetooth", "спри bluetooth", "спри блутут", "изключи bluetooth", "изключи блутут"):
            if not self.safety.confirm(
                "Disable Bluetooth devices",
                "This may disconnect headphones, mice, keyboards, and controllers.",
            ):
                return self._finalize(CommandResult(False, "Bluetooth disable cancelled."), classification)
            return self._finalize(self.actions.disable_bluetooth(), classification)

        adaptive_goal = self._extract_adaptive_workflow_goal(text)
        if adaptive_goal:
            adaptive_result = self._run_adaptive_ai_workflow(adaptive_goal)
            if adaptive_result is not None:
                return adaptive_result

        workflow_plan = self._plan_ai_workflow(text)
        if workflow_plan is not None:
            return self._handle_workflow_plan(workflow_plan)

        if not tried_conversation_first_intent:
            parsed_intent = self._parse_ai_intent(text)
            if parsed_intent is not None:
                return self._handle_parsed_intent(text, parsed_intent)

        if self._is_knowledge_question(text):
            if self.ai is None:
                return self._finalize(CommandResult(False, "AI answers are not configured yet."), classification)
            result = self.ai.answer_with_web_search(text)
            self._remember_conversation(text, result)
            return self._finalize(result, classification)

        if self.ai is not None and not self._looks_like_unsupported_action(text):
            result = self._answer_conversation(text)
            self._remember_conversation(text, result)
            return self._finalize(result, classification)

        return self._finalize(CommandResult(False, "I do not know that command yet."), classification)

    def _open(self, target: str) -> CommandResult:
        site_search = self._extract_site_search(target)
        if site_search is not None:
            query, site_name = site_search
            site = find_site(site_name)
            if site is not None:
                candidate = site_search_candidate(site, query)
                self.web_context.save_candidates([candidate], query=f"{query} in {site.title}")
                return self.actions.open_url(candidate.url)

        if target in self.settings.website_aliases:
            return self.actions.open_url(self.settings.website_aliases[target])

        if target in self.settings.app_aliases:
            return self.actions.open_app(self.settings.app_aliases[target], display_name=target)

        if self._contains_any(target, "windows update", "ъпдейт", "актуализации"):
            return self.actions.open_windows_update()

        if self._contains_any(target, "nvidia", "нвидиа"):
            return self.actions.open_nvidia_driver_page()

        if self._contains_any(target, "nitrosense", "nitro sense", "нитросенс", "нитро сенс"):
            return self.actions.open_nitrosense()

        if self._contains_any(target, "last file", "recent file", "последния файл", "последния документ"):
            return self.actions.open_recent_file()

        for name, url in WEBSITES.items():
            if name in target:
                return self.actions.open_url(url)

        for name, command in sorted(APP_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if name in target:
                return self.actions.open_app(command, display_name=name)

        discovered = self.actions.open_discovered_app(target)
        if discovered.ok:
            return discovered

        domain = self._target_to_domain(target)
        if domain:
            return self.actions.open_url(domain)

        if self._looks_like_url(target):
            return self.actions.open_url(target)

        return self.actions.search_web(target)

    def _show_deal_candidates(self, query: str) -> CommandResult:
        candidates = deal_candidates(query)
        self.web_context.save_candidates(candidates, query=f"deals {query}".strip())
        lines: list[str] = []
        if self.ai is not None and not getattr(self.ai, "dry_run", False):
            question = (
                "Провери актуално в кои български онлайн магазини има намаления"
                f" за {query or 'техника и gaming продукти'}. "
                "Отговори кратко на български и спомени, че мога да кажа 'отвори първия', "
                "ако искам да отворя първия запазен резултат."
            )
            ai_result = self.ai.answer_with_web_search(question)
            if ai_result.ok:
                lines.append(ai_result.message)
                lines.append("")
        lines.append("I saved store searches. Say 'open the first' / 'отвори първия':")
        for index, candidate in enumerate(candidates[:6], start=1):
            lines.append(f"{index}. {candidate.title}")
        return CommandResult(True, "\n".join(lines), metadata={"candidates": [candidate.url for candidate in candidates]})

    def _open_saved_candidate(self, ordinal: int) -> CommandResult:
        candidate = self.web_context.pick(ordinal)
        if candidate is None:
            return CommandResult(False, "I do not have a saved web result for that number yet.")
        return self.actions.open_url(candidate.url)

    def _read_saved_candidate(self, ordinal: int) -> CommandResult:
        candidate = self.web_context.pick(ordinal)
        if candidate is None:
            return CommandResult(False, "I do not have a saved web result for that number yet.")
        return self._read_url_and_record(candidate.url, ordinal=ordinal)

    def _read_matching_saved_candidate(self, query: str) -> CommandResult:
        match = self.web_context.find(query)
        if match is None:
            return CommandResult(False, f"I do not have a saved web result matching: {query}")
        ordinal, candidate = match
        result = self._read_url_and_record(candidate.url, ordinal=ordinal, match_query=query)
        return result.with_metadata(
            metadata={
                **result.metadata,
                "match_query": query,
                "ordinal": ordinal,
                "title": candidate.title,
                "url": candidate.url,
            }
        )

    def _read_url_and_record(
        self,
        url: str,
        *,
        ordinal: int | None = None,
        match_query: str = "",
    ) -> CommandResult:
        result = self.page_reader.extract(url)
        if result.ok:
            self.web_context.record_read(
                url=str(result.metadata.get("url", url)),
                title=str(result.metadata.get("title", "")),
                excerpt=str(result.metadata.get("excerpt", "")),
                text_length=int(result.metadata.get("text_length") or 0),
                ordinal=ordinal,
                match_query=match_query,
            )
        return result.with_metadata(
            metadata={
                **result.metadata,
                "browser_session_recorded": bool(result.ok),
                "ordinal": ordinal,
                "match_query": match_query,
            }
        )

    def _show_browser_session(self) -> CommandResult:
        summary = self.web_context.session_summary()
        candidates = summary["candidates"]
        opened = summary["opened"]
        read_pages = summary["read_pages"]
        if not candidates and not opened and not read_pages:
            return CommandResult(True, "I do not have an active browser session yet.", metadata={"browser_session": summary})
        lines = [f"Current browser session: {summary.get('query') or 'no saved query'}"]
        if candidates:
            lines.append("Saved results:")
            for index, candidate in enumerate(candidates[:6], start=1):
                lines.append(f"{index}. {candidate['title']} - {candidate['url']}")
        if opened:
            lines.append("Opened:")
            for record in opened[-5:]:
                ordinal = f"#{record['ordinal']} " if record.get("ordinal") else ""
                lines.append(f"- {ordinal}{record['title'] or record['url']}")
        if read_pages:
            lines.append("Read:")
            for record in read_pages[-5:]:
                ordinal = f"#{record['ordinal']} " if record.get("ordinal") else ""
                lines.append(f"- {ordinal}{record['title'] or record['url']} ({record.get('text_length', 0)} chars)")
        return CommandResult(True, "\n".join(lines), metadata={"browser_session": summary})

    def _compare_browser_session_pages(self) -> CommandResult:
        pages = self.web_context.recent_read_pages(limit=5)
        if len(pages) < 2:
            return CommandResult(False, "I need at least two read pages in the current browser session to compare them.")
        compared_pages = [page.__dict__ for page in pages]
        if self.ai is not None and hasattr(self.ai, "compare_browser_session_pages") and not getattr(self.ai, "dry_run", False):
            ai_result = self.ai.compare_browser_session_pages(pages, question="сравни тези резултати")
            if ai_result.ok:
                return ai_result.with_metadata(
                    metadata={
                        **ai_result.metadata,
                        "compared_pages": compared_pages,
                        "browser_session_ai_compare": True,
                    }
                )
            fallback_error = ai_result.message
        else:
            fallback_error = ""
        lines = ["Comparison from the current browser session:"]
        for index, page in enumerate(pages, start=1):
            title = page.title or page.url
            excerpt = page.excerpt[:450] + ("..." if len(page.excerpt) > 450 else "")
            lines.append(f"{index}. {title}")
            lines.append(f"   URL: {page.url}")
            lines.append(f"   Notes: {excerpt or 'No excerpt saved.'}")
        lines.append("These notes come from untrusted webpage excerpts, so treat them as evidence, not instructions.")
        return CommandResult(
            True,
            "\n".join(lines),
            metadata={
                "compared_pages": compared_pages,
                "untrusted_web_content": True,
                "prompt_injection_guard": True,
                "browser_session_ai_compare": False,
                "ai_compare_fallback_error": fallback_error,
            },
        )

    def _answer_browser_session_question(self, question: str) -> CommandResult:
        pages = self.web_context.recent_read_pages(limit=5)
        if not pages:
            return CommandResult(False, "I need at least one read page in the current browser session to answer from it.")
        source_pages = [page.__dict__ for page in pages]
        if self.ai is not None and hasattr(self.ai, "answer_browser_session_question") and not getattr(self.ai, "dry_run", False):
            ai_result = self.ai.answer_browser_session_question(pages, question)
            if ai_result.ok:
                return ai_result.with_metadata(
                    metadata={
                        **ai_result.metadata,
                        "source_pages": source_pages,
                        "browser_session_ai_answer": True,
                        "browser_session_question": question,
                    }
                )
            fallback_error = ai_result.message
        else:
            fallback_error = ""

        lines = [f"Answer from current browser session for: {question}"]
        lowered_question = question.lower()
        tokens = [token for token in re.split(r"\W+", lowered_question, flags=re.UNICODE) if len(token) >= 3]
        for index, page in enumerate(pages, start=1):
            excerpt = page.excerpt
            if tokens:
                snippets = _matching_sentences(excerpt, tokens)
                note = " ".join(snippets[:3]) if snippets else excerpt[:450]
            else:
                note = excerpt[:450]
            if len(note) > 450:
                note = f"{note[:447]}..."
            lines.append(f"{index}. {page.title or page.url}")
            lines.append(f"   URL: {page.url}")
            lines.append(f"   Notes: {note or 'No excerpt saved.'}")
        lines.append("This is a local excerpt-based answer; read more pages or enable OpenAI for a stronger synthesis.")
        return CommandResult(
            True,
            "\n".join(lines),
            metadata={
                "source_pages": source_pages,
                "browser_session_question": question,
                "browser_session_ai_answer": False,
                "ai_answer_fallback_error": fallback_error,
                "untrusted_web_content": True,
                "prompt_injection_guard": True,
            },
        )

    def _run_open_first_deal_workflow(self, query: str) -> CommandResult:
        candidates = deal_candidates(query)
        if not candidates:
            return CommandResult(False, f"I could not prepare deal searches for: {query}")
        first = candidates[0]
        return self.workflow_runner.run(
            "open_first_deal",
            [
                WorkflowStep("Prepare deal search candidates", ToolCall("save_deal_candidates", {"query": query})),
                WorkflowStep(f"Open first candidate: {first.title}", ToolCall("open_url", {"url": first.url})),
            ],
            confirm=lambda spec, call: self.safety.confirm(
                f"Run workflow step: {spec.name}",
                f"{spec.description} Arguments: {call.arguments}",
            ),
        )

    def _plan_ai_workflow(self, text: str) -> WorkflowPlan | None:
        if self.ai is None or not self._looks_like_workflow_request(text):
            return None
        if not hasattr(self.ai, "plan_workflow"):
            return None
        plan = self.ai.plan_workflow(text, self.tools, history=self.conversation_memory.recent())
        if not plan.ok:
            return None
        return plan

    def _handle_workflow_plan(self, plan: WorkflowPlan) -> CommandResult:
        preview = preview_workflow_plan(plan, self.tools)
        classification = self._classify_workflow_plan(plan)
        if preview.requires_approval and not self.safety.confirm(
            f"Run workflow plan: {plan.name}",
            preview.to_message(),
        ):
            return self._finalize(
                CommandResult(
                    False,
                    f"Workflow plan cancelled: {plan.name}\n{preview.to_message()}",
                    metadata=self._workflow_preview_metadata(preview, plan.reason, plan.metadata),
                ),
                classification,
            )

        result = self.workflow_runner.run(
            plan.name,
            plan.steps,
            confirm=lambda spec, call: self.safety.confirm(
                f"Run workflow step: {spec.name}",
                f"{spec.description} Arguments: {call.arguments}",
            ),
            max_retries=1,
            retryable_tools=WORKFLOW_RETRYABLE_TOOLS,
        )
        return self._finalize(
            result.with_metadata(metadata={**self._workflow_preview_metadata(preview, plan.reason, plan.metadata), **result.metadata}),
            classification,
        )

    def _run_adaptive_ai_workflow(self, goal: str) -> CommandResult | None:
        if self.ai is None or not hasattr(self.ai, "decide_next_workflow_step"):
            return None
        result = self.workflow_runner.run_adaptive(
            "adaptive_agent",
            goal,
            decide_next=lambda previous_steps: self.ai.decide_next_workflow_step(
                goal,
                self.tools,
                previous_steps,
                history=self.conversation_memory.recent(),
            ),
            confirm=lambda spec, call: self.safety.confirm(
                f"Run adaptive workflow step: {spec.name}",
                f"{spec.description} Arguments: {call.arguments}",
            ),
            max_retries=1,
            retryable_tools=WORKFLOW_RETRYABLE_TOOLS,
            recover_safe_failures=True,
            max_steps=8,
            preview=bool(getattr(self.actions, "dry_run", False)),
        )
        return self._finalize(
            result,
            IntentMetadata("llm.adaptive_workflow", "adaptive_agent", self._workflow_result_permission(result), self._workflow_result_requires_confirmation(result)),
        )

    @staticmethod
    def _workflow_result_permission(result: CommandResult) -> str:
        permissions = [
            str(step.get("permission", SAFE))
            for step in result.metadata.get("workflow_steps", [])
            if isinstance(step, dict)
        ]
        if not permissions:
            return SAFE
        order = {SAFE: 0, ADMIN: 1, CONFIRM: 2, BLOCKED: 3}
        return max(permissions, key=lambda permission: order.get(permission, 3))

    @staticmethod
    def _workflow_result_requires_confirmation(result: CommandResult) -> bool:
        return any(
            bool(step.get("requires_confirmation"))
            for step in result.metadata.get("workflow_steps", [])
            if isinstance(step, dict)
        )

    @staticmethod
    def _workflow_preview_metadata(preview: WorkflowPlanPreview, reason: str, planner_metadata: dict[str, object] | None = None) -> dict:
        return {
            "workflow_reason": reason,
            "workflow_planner_metadata": planner_metadata or {},
            "workflow_preview": preview.lines,
            "workflow_requires_approval": preview.requires_approval,
            "workflow_highest_permission": preview.highest_permission,
            "workflow_risky_tools": preview.risky_tools,
            "workflow_step_count": preview.step_count,
            "workflow_steps": [],
        }

    def _classify_workflow_plan(self, plan: WorkflowPlan) -> IntentMetadata:
        specs = [self.tools.get(step.tool_call.name).spec for step in plan.steps if self.tools.get(step.tool_call.name) is not None]
        requires_confirmation = any(spec.requires_confirmation for spec in specs)
        if requires_confirmation:
            permission = CONFIRM
        elif any(spec.permission == ADMIN for spec in specs):
            permission = ADMIN
        else:
            permission = SAFE
        return IntentMetadata("llm.workflow", plan.name, permission, requires_confirmation)

    def _remember_fact(self, content: str, category: str = "general", importance: int = 3) -> CommandResult:
        redaction = redact_sensitive_text(content)
        try:
            item = self.long_term_memory.remember(content, category=category, importance=importance)
        except ValueError as exc:
            return CommandResult(False, str(exc))
        return CommandResult(
            True,
            f"I will remember that: {item.content}",
            metadata={
                "memory_id": item.id,
                "memory_category": item.category,
                "memory_importance": item.importance,
                "privacy_redacted": redaction.redacted,
                "privacy_findings": list(redaction.findings),
            },
        )

    def _set_user_preference(self, key: str, value: object) -> CommandResult:
        try:
            normalized_key, normalized_value = self.settings.set_user_preference(key, value)
            self.settings.save(self.settings_path)
        except (TypeError, ValueError) as exc:
            return CommandResult(False, str(exc))
        return CommandResult(
            True,
            f"Saved preference: {normalized_key} = {normalized_value}",
            metadata={
                "preference_key": normalized_key,
                "preference_value": normalized_value,
                "preferences": self.settings.user_preference_summary(),
            },
        )

    def _show_user_preferences(self) -> CommandResult:
        preferences = self.settings.user_preference_summary()
        if not preferences:
            return CommandResult(True, "No personal preferences are saved yet.", metadata={"preferences": {}})
        lines = ["Saved personal preferences:"]
        labels = {
            "address_name": "How I address you",
            "preferred_browser": "Preferred browser",
            "preferred_volume": "Preferred volume",
        }
        for key, value in preferences.items():
            lines.append(f"- {labels.get(key, key)}: {value}")
        return CommandResult(True, "\n".join(lines), metadata={"preferences": preferences})

    def _apply_preferred_volume(self) -> CommandResult:
        value = self.settings.mode_preferences.get("preferred_volume")
        if value is None:
            return CommandResult(False, "Preferred volume is not saved yet.")
        try:
            percent = int(value)
        except (TypeError, ValueError):
            return CommandResult(False, f"Preferred volume is invalid: {value}")
        result = self.actions.set_volume(percent)
        return result.with_metadata(metadata={**result.metadata, "preferred_volume": max(0, min(100, percent))})

    def _update_memory(
        self,
        memory_id: int,
        *,
        content: str | None = None,
        category: str | None = None,
        importance: int | None = None,
    ) -> CommandResult:
        redaction = redact_sensitive_text(content) if content is not None else None
        try:
            item = self.long_term_memory.update(
                memory_id,
                content=content,
                category=category,
                importance=importance,
            )
        except ValueError as exc:
            return CommandResult(False, str(exc))
        if item is None:
            return CommandResult(False, f"I did not find memory #{memory_id}.")
        return CommandResult(
            True,
            f"Updated memory #{item.id}: [{item.category}] {item.content}",
            metadata={
                "memory_id": item.id,
                "memory_category": item.category,
                "memory_importance": item.importance,
                "privacy_redacted": bool(redaction and redaction.redacted),
                "privacy_findings": list(redaction.findings) if redaction else [],
            },
        )

    def _list_memory_categories(self) -> CommandResult:
        counts = self.long_term_memory.list_categories()
        lines = ["Memory categories:"]
        lines.extend(f"- {category}: {count}" for category, count in counts.items())
        return CommandResult(True, "\n".join(lines), metadata={"memory_categories": counts})

    def _forget_memory(self, query: str) -> CommandResult:
        deleted = self.long_term_memory.forget(query)
        if deleted == 0:
            return CommandResult(False, f"I did not find a memory matching: {query}")
        return CommandResult(True, f"Forgot {deleted} matching memory item(s).", metadata={"deleted_memories": deleted})

    def _show_memory(self, query: str = "") -> CommandResult:
        memories = self.long_term_memory.search(query=query)
        if not memories:
            return CommandResult(True, "I do not have saved memories matching that yet.", metadata={"memories": []})
        lines = ["Here is what I remember:"]
        for item in memories:
            lines.append(f"- [{item.category}] {item.content}")
        return CommandResult(
            True,
            "\n".join(lines),
            metadata={"memories": [item.content for item in memories], "memory_count": len(memories)},
        )

    def _summarize_conversation_episode(self) -> CommandResult:
        return self.episodic_memory.summarize_conversation(
            self.conversation_memory.recent(limit=80),
            ai=self.ai,
            force=True,
        )

    def _summarize_action_episode(self, minutes: int) -> CommandResult:
        safe_minutes = max(1, min(1440, minutes))
        records = self.audit_reader.recent(minutes=safe_minutes, limit=100)
        return self.episodic_memory.summarize_actions(records, minutes=safe_minutes)

    def _answer_conversation(self, message: str) -> CommandResult:
        if self.ai is None:
            return CommandResult(False, "AI conversation is not configured yet.")
        history = self.conversation_memory.recent()
        memory_context = self._conversation_memory_context(message)
        try:
            parameters = inspect.signature(self.ai.answer_conversation).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "memory_context" in parameters:
            result = self.ai.answer_conversation(message, history=history, memory_context=memory_context)
        else:
            result = self.ai.answer_conversation(message, history=history)
        if not memory_context:
            return result
        return result.with_metadata(
            metadata={
                **result.metadata,
                "memory_context_hits": memory_context,
                "memory_context_count": len(memory_context),
            }
        )

    def _conversation_memory_context(self, message: str) -> list[dict[str, object]]:
        if not _setting_enabled(self.settings.openai.get("use_memory_context", True)):
            return []
        hits = self.semantic_memory.search(message, limit=4)
        context = [hit.to_dict() for hit in hits if hit.score >= 0.18]
        preference_summary = self.settings.user_preference_summary()
        if preference_summary and self._is_preference_related_message(message):
            context.append(
                {
                    "kind": "settings_preference",
                    "score": 0.5,
                    "content": ", ".join(f"{key}: {value}" for key, value in preference_summary.items()),
                }
            )
        return context

    @staticmethod
    def _is_preference_related_message(message: str) -> bool:
        return any(
            word in message
            for word in (
                "preference",
                "preferred",
                "favorite",
                "browser",
                "volume",
                "name",
                "предпочит",
                "любим",
                "браузър",
                "звук",
                "име",
                "наричаш",
            )
        )

    def _show_action_history(self, minutes: int) -> CommandResult:
        records = self.audit_reader.recent(minutes=minutes)
        return CommandResult(
            True,
            self.audit_reader.summarize_recent(minutes=minutes),
            metadata={
                "action_history_minutes": minutes,
                "action_history_count": len(records),
                "actions": [record.action for record in records],
            },
        )

    def _show_filtered_traces(
        self,
        *,
        minutes: int = 24 * 60,
        limit: int = 20,
        source: str = "",
        intent: str = "",
        action: str = "",
        permission: str = "",
        ok: bool | None = None,
        error_type: str = "",
        recommended_action: str = "",
    ) -> CommandResult:
        records = self.audit_reader.filtered(
            minutes=minutes,
            limit=limit,
            source=source,
            intent=intent,
            action=action,
            permission=permission,
            ok=ok,
            error_type=error_type,
            recommended_action=recommended_action,
        )
        trace_filter = {
            "minutes": minutes,
            "limit": limit,
            "source": source,
            "intent": intent,
            "action": action,
            "permission": permission,
            "ok": ok,
            "error_type": error_type,
            "recommended_action": recommended_action,
        }
        return CommandResult(
            True,
            self.audit_reader.summarize_filtered(**trace_filter),
            metadata={
                "trace_filter": trace_filter,
                "trace_filter_count": len(records),
                "traces": [
                    {
                        "timestamp": record.timestamp,
                        "source": record.source,
                        "raw_text": record.raw_text,
                        "intent": record.intent,
                        "action": record.action,
                        "permission": record.permission,
                        "ok": record.ok,
                        "latency_ms": record.latency_ms,
                        "metadata": record.metadata or {},
                    }
                    for record in records
                ],
            },
        )

    def _show_latest_trace(self) -> CommandResult:
        record = self.audit_reader.latest_trace()
        return CommandResult(
            True,
            self.audit_reader.summarize_latest_trace(),
            metadata={
                "trace_available": record is not None,
                "trace_action": record.action if record else "",
                "trace_intent": record.intent if record else "",
            },
        )

    def _parse_ai_intent(self, text: str) -> ParsedIntent | None:
        if self.ai is None:
            return None
        parsed = self.ai.parse_intent(text, self.tools, history=self.conversation_memory.recent())
        if parsed.kind == "unknown":
            return None
        return parsed

    def _should_keep_local_rule_before_ai(self, text: str, classification: IntentMetadata) -> bool:
        if classification.permission == BLOCKED:
            return True
        if classification.requires_confirmation and classification.action in {
            "restart",
            "shutdown",
            "sleep",
            "cleanup_temp_files",
            "game_mode",
            "enable_internet",
            "disable_internet",
            "enable_bluetooth",
            "disable_bluetooth",
        }:
            return True
        return self._contains_any(
            text,
            "undo",
            "rollback",
            "върни последното",
            "отмени последното",
        )

    def _handle_parsed_intent(self, text: str, parsed: ParsedIntent) -> CommandResult:
        if parsed.kind == "web_answer":
            clarification = self._intent_clarification(parsed)
            if clarification is not None:
                return self._finalize(clarification, IntentMetadata("llm.clarification", "ask_clarification", SAFE))
            if self.ai is None:
                return self._finalize(
                    CommandResult(False, "AI answers are not configured yet."),
                    IntentMetadata("llm.web_answer", "answer_with_web_search", SAFE),
                )
            result = self.ai.answer_with_web_search(parsed.message or text)
            self._remember_conversation(text, result)
            return self._finalize(
                result.with_metadata(metadata={**result.metadata, "intent_reason": parsed.reason, "intent_parser_metadata": parsed.metadata}),
                IntentMetadata("llm.web_answer", "answer_with_web_search", SAFE),
            )

        if parsed.kind == "conversation":
            if self.ai is None:
                return self._finalize(
                    CommandResult(False, "AI answers are not configured yet."),
                    IntentMetadata("llm.conversation", "answer_conversation", SAFE),
                )
            result = self._answer_conversation(parsed.message or text)
            self._remember_conversation(text, result)
            return self._finalize(
                result.with_metadata(metadata={**result.metadata, "intent_reason": parsed.reason, "intent_parser_metadata": parsed.metadata}),
                IntentMetadata("llm.conversation", "answer_conversation", SAFE),
            )

        tool_call = parsed.to_tool_call()
        if tool_call is None:
            return self._finalize(
                CommandResult(False, "I could not turn that into a safe Jarvis action."),
                IntentMetadata("llm.unknown", "unknown", SAFE),
            )

        registered = self.tools.get(tool_call.name)
        if registered is None:
            return self._finalize(
                CommandResult(
                    False,
                    f"That tool is not registered: {tool_call.name}",
                    metadata={
                        "llm_tool_trace": self._llm_tool_trace(
                            parsed=parsed,
                            tool_call=tool_call,
                            status="unregistered_tool",
                        ),
                        "intent_parser_metadata": parsed.metadata,
                    },
                ),
                IntentMetadata("llm.unknown_tool", tool_call.name, BLOCKED),
            )

        spec = registered.spec
        classification = IntentMetadata(
            f"llm.tool.{spec.name}",
            spec.name,
            spec.permission,
            spec.requires_confirmation,
        )
        argument_clarification = self._tool_argument_clarification(parsed, spec=spec, tool_call=tool_call)
        if argument_clarification is not None:
            missing = argument_clarification.metadata.get("missing_arguments", [])
            first_missing = str(missing[0]) if isinstance(missing, list) and missing else ""
            param = next((param for param in getattr(spec, "parameters", ()) if param.name == first_missing), None)
            self._pending_clarification = PendingClarification(
                parsed=parsed,
                tool_call=tool_call,
                question=str(argument_clarification.metadata.get("clarification_question", "")),
                fill_argument=first_missing,
                fill_type=str(getattr(param, "type", "string")),
            )
            return self._finalize(argument_clarification, IntentMetadata("llm.argument_clarification", "ask_tool_argument", SAFE))

        clarification = self._intent_clarification(parsed, spec=spec, tool_call=tool_call)
        if clarification is not None:
            self._pending_clarification = PendingClarification(
                parsed=parsed,
                tool_call=tool_call,
                question=str(clarification.metadata.get("clarification_question", "")),
            )
            return self._finalize(clarification, IntentMetadata("llm.clarification", "ask_clarification", SAFE))

        return self._execute_llm_tool_call(parsed, tool_call, spec, classification)

    def _execute_llm_tool_call(
        self,
        parsed: ParsedIntent,
        tool_call: ToolCall,
        spec: object,
        classification: IntentMetadata,
        *,
        clarification_resolved: bool = False,
    ) -> CommandResult:
        level_blocked = self.tools.level_block(spec)
        if level_blocked is not None:  # before any confirmation dialog opens
            return self._finalize(level_blocked, classification)
        if spec.requires_confirmation and not self.safety.confirm(
            f"Run Jarvis tool: {spec.name}",
            f"{spec.description} Arguments: {tool_call.arguments}",
        ):
            return self._finalize(
                CommandResult(
                    False,
                    f"{spec.name} cancelled.",
                    metadata={
                        "llm_tool_trace": self._llm_tool_trace(
                            parsed=parsed,
                            tool_call=tool_call,
                            spec=spec,
                            status="cancelled",
                        ),
                        "intent_parser_metadata": parsed.metadata,
                        "clarification_resolved": clarification_resolved,
                    },
                ),
                classification,
            )

        result = self.tools.execute(tool_call)
        from .trusted_actions import trusted_local_action
        if spec.requires_confirmation and trusted_local_action(self.settings, spec.name):
            result = result.with_metadata(metadata={**result.metadata, "approval_source": "trusted_local_setting"})
        return self._finalize(
            result.with_metadata(
                metadata={
                    **result.metadata,
                    "intent_reason": parsed.reason,
                    "intent_parser_metadata": parsed.metadata,
                    "clarification_resolved": clarification_resolved,
                    "llm_tool_trace": self._llm_tool_trace(
                        parsed=parsed,
                        tool_call=tool_call,
                        spec=spec,
                        status="executed",
                        result=result,
                    ),
                }
            ),
            classification,
        )

    def _handle_pending_clarification(self, text: str) -> CommandResult | None:
        pending = self._pending_clarification
        if pending is None:
            return None
        if pending.fill_argument:
            if self._is_negative_reply(text):
                self._pending_clarification = None
                return self._finalize(
                    CommandResult(
                        False,
                        "Pending tool argument cancelled.",
                        metadata={
                            "clarification_resolved": False,
                            "clarification_question": pending.question,
                            "missing_arguments": [pending.fill_argument],
                            "llm_tool_trace": self._llm_tool_trace(
                                parsed=pending.parsed,
                                tool_call=pending.tool_call,
                                status="argument_cancelled",
                            ),
                        },
                    ),
                    IntentMetadata("llm.argument_cancelled", "ask_tool_argument", SAFE),
                )
            value = self._coerce_pending_argument(text, pending.fill_type)
            if value is None:
                self._pending_clarification = None
                return self._finalize(
                    CommandResult(
                        False,
                        f"I could not use that value for {pending.fill_argument}.",
                        metadata={
                            "clarification_resolved": False,
                            "clarification_question": pending.question,
                            "missing_arguments": [pending.fill_argument],
                        },
                    ),
                    IntentMetadata("llm.argument_cancelled", "ask_tool_argument", SAFE),
                )
            self._pending_clarification = None
            arguments = {**pending.tool_call.arguments, pending.fill_argument: value}
            tool_call = ToolCall(pending.tool_call.name, arguments)
            registered = self.tools.get(tool_call.name)
            if registered is None:
                return self._finalize(
                    CommandResult(False, f"That tool is no longer registered: {tool_call.name}"),
                    IntentMetadata("llm.argument_resolved", tool_call.name, BLOCKED),
                )
            spec = registered.spec
            return self._execute_llm_tool_call(
                pending.parsed,
                tool_call,
                spec,
                IntentMetadata(f"llm.tool.{spec.name}", spec.name, spec.permission, spec.requires_confirmation),
                clarification_resolved=True,
            )
        if self._is_affirmative_reply(text):
            self._pending_clarification = None
            registered = self.tools.get(pending.tool_call.name)
            if registered is None:
                return self._finalize(
                    CommandResult(False, f"That tool is no longer registered: {pending.tool_call.name}"),
                    IntentMetadata("llm.clarification_resolved", pending.tool_call.name, BLOCKED),
                )
            spec = registered.spec
            return self._execute_llm_tool_call(
                pending.parsed,
                pending.tool_call,
                spec,
                IntentMetadata(f"llm.tool.{spec.name}", spec.name, spec.permission, spec.requires_confirmation),
                clarification_resolved=True,
            )
        if self._is_negative_reply(text):
            self._pending_clarification = None
            return self._finalize(
                CommandResult(
                    False,
                    "Clarified action cancelled.",
                    metadata={
                        "clarification_resolved": False,
                        "clarification_question": pending.question,
                        "llm_tool_trace": self._llm_tool_trace(
                            parsed=pending.parsed,
                            tool_call=pending.tool_call,
                            status="clarification_cancelled",
                        ),
                    },
                ),
                IntentMetadata("llm.clarification_cancelled", "ask_clarification", SAFE),
            )
        self._pending_clarification = None
        return None

    @staticmethod
    def _llm_tool_trace(
        *,
        parsed: ParsedIntent,
        tool_call: ToolCall,
        status: str,
        spec: object | None = None,
        result: CommandResult | None = None,
    ) -> dict[str, object]:
        return {
            "source": "llm_intent_parser",
            "status": status,
            "reason": parsed.reason,
            "confidence": parsed.confidence,
            "clarification_question": parsed.clarification_question,
            "selected_tool": tool_call.name,
            "arguments": tool_call.arguments,
            "permission": getattr(spec, "permission", BLOCKED),
            "requires_confirmation": bool(getattr(spec, "requires_confirmation", True)),
            "result_ok": result.ok if result is not None else None,
            "result_message": result.message if result is not None else "",
        }

    @staticmethod
    def _intent_clarification(
        parsed: ParsedIntent,
        *,
        spec: object | None = None,
        tool_call: ToolCall | None = None,
    ) -> CommandResult | None:
        if parsed.kind == "conversation":
            return None
        permission = str(getattr(spec, "permission", SAFE))
        threshold = 0.5 if parsed.kind == "web_answer" else 0.65
        if permission in {ADMIN, CONFIRM, BLOCKED}:
            threshold = 0.75
        needs_clarification = bool(parsed.clarification_question) or parsed.confidence < threshold
        if not needs_clarification:
            return None
        question = parsed.clarification_question or "Can you clarify exactly what you want Jarvis to do?"
        metadata = {
            "intent_reason": parsed.reason,
            "intent_confidence": parsed.confidence,
            "clarification_question": question,
            "intent_parser_metadata": parsed.metadata,
        }
        if tool_call is not None:
            metadata["llm_tool_trace"] = {
                "source": "llm_intent_parser",
                "status": "needs_clarification",
                "reason": parsed.reason,
                "confidence": parsed.confidence,
                "clarification_question": question,
                "selected_tool": tool_call.name,
                "arguments": tool_call.arguments,
                "permission": permission,
                "requires_confirmation": bool(getattr(spec, "requires_confirmation", True)),
                "result_ok": None,
                "result_message": "",
            }
        return CommandResult(
            False,
            f"I need clarification before acting: {question}",
            metadata=metadata,
        )

    @staticmethod
    def _tool_argument_clarification(
        parsed: ParsedIntent,
        *,
        spec: object,
        tool_call: ToolCall,
    ) -> CommandResult | None:
        parameters = tuple(getattr(spec, "parameters", ()))
        missing, unexpected = validate_tool_arguments(spec, tool_call.arguments)
        if unexpected:
            return CommandResult(
                False,
                f"I cannot safely run {tool_call.name}: unexpected argument(s): {', '.join(unexpected)}.",
                metadata={
                    "intent_reason": parsed.reason,
                    "intent_confidence": parsed.confidence,
                    "unexpected_arguments": unexpected,
                    "intent_parser_metadata": parsed.metadata,
                    "llm_tool_trace": {
                        "source": "llm_intent_parser",
                        "status": "unexpected_arguments",
                        "reason": parsed.reason,
                        "confidence": parsed.confidence,
                        "selected_tool": tool_call.name,
                        "arguments": tool_call.arguments,
                        "unexpected_arguments": unexpected,
                        "permission": getattr(spec, "permission", BLOCKED),
                        "requires_confirmation": bool(getattr(spec, "requires_confirmation", True)),
                        "result_ok": None,
                        "result_message": "",
                    },
                },
            )
        if not missing:
            return None
        first_missing = missing[0]
        param = next((param for param in parameters if param.name == first_missing), None)
        description = str(getattr(param, "description", first_missing))
        question = f"What should I use for {first_missing}? {description}"
        return CommandResult(
            False,
            f"I need a tool argument before acting: {question}",
            metadata={
                "intent_reason": parsed.reason,
                "intent_confidence": parsed.confidence,
                "clarification_question": question,
                "missing_arguments": missing,
                "intent_parser_metadata": parsed.metadata,
                "llm_tool_trace": {
                    "source": "llm_intent_parser",
                    "status": "missing_arguments",
                    "reason": parsed.reason,
                    "confidence": parsed.confidence,
                    "clarification_question": question,
                    "selected_tool": tool_call.name,
                    "arguments": tool_call.arguments,
                    "missing_arguments": missing,
                    "permission": getattr(spec, "permission", BLOCKED),
                    "requires_confirmation": bool(getattr(spec, "requires_confirmation", True)),
                    "result_ok": None,
                    "result_message": "",
                },
            },
        )

    @staticmethod
    def _coerce_pending_argument(text: str, argument_type: str) -> object | None:
        cleaned = text.strip()
        if not cleaned:
            return None
        if argument_type == "integer":
            match = re.search(r"-?\d+", cleaned)
            return int(match.group(0)) if match else None
        if argument_type == "number":
            match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
            return float(match.group(0)) if match else None
        if argument_type == "boolean":
            if cleaned in {"yes", "true", "1", "да", "ok", "okay"}:
                return True
            if cleaned in {"no", "false", "0", "не"}:
                return False
            return None
        return cleaned

    def _finalize(self, result: CommandResult, classification: IntentMetadata) -> CommandResult:
        error = "" if result.ok else result.message
        finalized = result.with_metadata(
            intent=classification.intent,
            action=classification.action,
            permission=classification.permission,
            requires_confirmation=classification.requires_confirmation,
            confirmed=confirmed_from_result(
                result.ok,
                result.message,
                classification.requires_confirmation,
            ),
            error=error,
        )
        return enrich_error_metadata(finalized)

    def _classify(self, text: str) -> IntentMetadata:
        if self._contains_any(
            text,
            "kernel",
            "ядро",
            "defender off",
            "disable defender",
            "спри defender",
            "спри защитата",
            "disable firewall",
            "спри firewall",
            "изключи firewall",
            "registry delete",
            "изтрий registry",
        ):
            return IntentMetadata("blocked.security_sensitive", "blocked", BLOCKED)

        if self._contains_any(text, "restart", "рестартирай"):
            return IntentMetadata("system.restart", "restart", CONFIRM, True)
        if self._contains_any(text, "shutdown", "изключи лаптопа", "изключи компютъра"):
            return IntentMetadata("system.shutdown", "shutdown", CONFIRM, True)
        if self._contains_any(text, "sleep", "приспи", "заспи"):
            return IntentMetadata("system.sleep", "sleep", CONFIRM, True)
        if self._contains_any(text, "clean temp", "clear temp", "почисти temp", "изчисти temp", "почисти временни"):
            return IntentMetadata("system.cleanup_temp", "cleanup_temp_files", CONFIRM, True)
        if self._contains_any(text, "режим игра", "game mode", "gaming mode"):
            return IntentMetadata("modes.gaming", "game_mode", CONFIRM, True)
        if self._contains_any(text, "internet on", "enable internet", "пусни интернета", "включи интернета"):
            return IntentMetadata("network.enable_internet", "enable_internet", ADMIN, True)
        if self._contains_any(text, "internet off", "disable internet", "спри интернета", "изключи интернета"):
            return IntentMetadata("network.disable_internet", "disable_internet", ADMIN, True)
        if self._contains_any(text, "bluetooth on", "enable bluetooth", "пусни bluetooth", "пусни блутут", "включи bluetooth", "включи блутут"):
            return IntentMetadata("bluetooth.enable", "enable_bluetooth", ADMIN, True)
        if self._contains_any(text, "bluetooth off", "disable bluetooth", "спри bluetooth", "спри блутут", "изключи bluetooth", "изключи блутут"):
            return IntentMetadata("bluetooth.disable", "disable_bluetooth", ADMIN, True)

        if self._contains_any(text, "list tools", "show tools", "available tools", "покажи tools", "покажи инструмент", "какви инструменти"):
            return IntentMetadata("developer.list_tools", "list_tools", SAFE)
        if self._extract_user_preference_set(text) is not None:
            return IntentMetadata("settings.set_preference", "set_user_preference", SAFE)
        if self._is_user_preferences_request(text):
            return IntentMetadata("settings.show_preferences", "show_user_preferences", SAFE)
        if self._extract_open_first_deal_workflow(text) is not None:
            return IntentMetadata("workflow.open_first_deal", "open_first_deal", SAFE)
        if self._extract_browser_search_and_open(text) is not None:
            return IntentMetadata("browser.search_and_open", "browser_search_and_open", SAFE)
        if self._extract_open_ordinal(text) is not None:
            return IntentMetadata("web.open_saved_candidate", "open_saved_candidate", SAFE)
        if self._extract_action_episode_minutes(text) is not None:
            return IntentMetadata("memory.action_episode_summarize", "summarize_action_episode", SAFE)
        if self._extract_action_history_minutes(text) is not None:
            return IntentMetadata("developer.action_history", "action_history", SAFE)
        if self._extract_trace_filter(text) is not None:
            return IntentMetadata("developer.trace_filter", "filtered_developer_traces", SAFE)
        if self._is_trace_request(text):
            return IntentMetadata("developer.latest_trace", "latest_developer_trace", SAFE)
        if self._is_voice_diagnostics_request(text):
            return IntentMetadata("voice.diagnostics", "voice_diagnostics", SAFE)
        if self._extract_read_ordinal(text) is not None:
            return IntentMetadata("browser.extract_saved_candidate", "extract_webpage", SAFE)
        if self._extract_read_matching_query(text) is not None:
            return IntentMetadata("browser.extract_matching_saved_candidate", "extract_saved_web_result_matching", SAFE)
        if self._extract_read_url(text):
            return IntentMetadata("browser.extract_webpage", "extract_webpage", SAFE)
        if self._is_browser_session_request(text):
            return IntentMetadata("browser.session_summary", "show_browser_session", SAFE)
        if self._is_browser_session_compare_request(text):
            return IntentMetadata("browser.session_compare", "compare_browser_session_pages", SAFE)
        if self._extract_browser_session_question(text) is not None:
            return IntentMetadata("browser.session_answer", "answer_browser_session_question", SAFE)
        if self._extract_research_query(text) is not None:
            return IntentMetadata("research.web", "research_web", SAFE)
        if self._extract_browser_search_query(text) is not None:
            return IntentMetadata("browser.search", "browser_search", SAFE)
        if self._is_browser_automation_status_request(text):
            return IntentMetadata("browser.automation_status", "browser_automation_status", SAFE)
        if self._is_screen_vision_status_request(text):
            return IntentMetadata("vision.status", "screen_vision_status", SAFE)
        if self._extract_screen_vision_prompt(text) is not None:
            return IntentMetadata("vision.screen_describe", "screen_describe", CONFIRM, True)
        if self._extract_categorized_remember(text):
            return IntentMetadata("memory.remember_categorized", "remember", SAFE)
        if self._extract_memory_update(text):
            return IntentMetadata("memory.update", "update_memory", SAFE)
        if self._extract_memory_category_update(text):
            return IntentMetadata("memory.set_category", "set_memory_category", SAFE)
        if self._is_memory_categories_request(text):
            return IntentMetadata("memory.categories", "list_memory_categories", SAFE)
        if self._extract_remember_text(text):
            return IntentMetadata("memory.remember", "remember", SAFE)
        if self._extract_forget_query(text):
            return IntentMetadata("memory.forget", "forget", SAFE)
        if self._is_episode_summary_request(text):
            return IntentMetadata("memory.episode_summarize", "summarize_conversation_episode", SAFE)
        if self._extract_semantic_memory_query(text) is not None:
            return IntentMetadata("memory.semantic_search", "semantic_memory_search", SAFE)
        if self._extract_episode_memory_query(text) is not None:
            return IntentMetadata("memory.episode_search", "list_episode_summaries", SAFE)
        if self._extract_memory_query(text) is not None:
            return IntentMetadata("memory.search", "search_memory", SAFE)
        if self._extract_deals_query(text) is not None:
            return IntentMetadata("shopping.deals", "show_deal_candidates", SAFE)
        if self._extract_open_matching_query(text) is not None:
            return IntentMetadata("browser.open_matching_result", "browser_open_matching_result", SAFE)
        if self._extract_open_target(text):
            return IntentMetadata("apps_or_web.open", "open_target", SAFE)
        if self._extract_volume_percent(text) is not None:
            return IntentMetadata("system.volume_set", "set_volume", SAFE)
        if self._is_apply_preferred_volume_request(text):
            return IntentMetadata("system.volume_set_preferred", "set_volume", SAFE)
        if self._contains_any(text, "volume up", "increase volume", "увеличи звука", "усили звука"):
            return IntentMetadata("system.volume_up", "volume_up", SAFE)
        if self._contains_any(text, "volume down", "decrease volume", "намали звука"):
            return IntentMetadata("system.volume_down", "volume_down", SAFE)
        if self._contains_any(text, "mute", "заглуши", "спри звука"):
            return IntentMetadata("system.mute_toggle", "toggle_mute", SAFE)
        if self._contains_any(text, "undo", "rollback", "върни последното", "отмени последното"):
            return IntentMetadata("system.undo", "undo_last_action", CONFIRM, True)
        if self._contains_any(text, "refresh app database", "refresh apps", "обнови приложенията", "сканирай приложенията"):
            return IntentMetadata("apps.refresh_database", "refresh_app_database", SAFE)
        if self._contains_any(text, "list app database", "list apps", "покажи приложенията", "списък с приложения"):
            return IntentMetadata("apps.list_database", "list_app_database", SAFE)
        if self._extract_mode(text):
            return IntentMetadata("modes.apply", "apply_mode", ADMIN)
        if self._contains_any(text, "open last file", "open recent file", "отвори последния файл", "отвори последния документ"):
            return IntentMetadata("files.open_recent", "open_recent_file", SAFE)
        if self._extract_docx_topic(text):
            return IntentMetadata("documents.create_docx", "create_docx", SAFE)
        if self._contains_any(text, "what is loading", "top processes", "какво ми товари", "какво товари", "натоварва компютъра"):
            return IntentMetadata("system.top_processes", "top_processes", SAFE)
        if self._contains_any(text, "startup programs", "startup apps", "стартъп програм", "стартиращи програм"):
            return IntentMetadata("system.startup_programs", "startup_programs", SAFE)
        if self._extract_temperature_threshold(text) is not None:
            return IntentMetadata("monitoring.temperature_warning", "temperature_warning", SAFE)
        if self._contains_any(text, "driver update", "driver updates", "ъпдейт на драйвер", "ъпдейти на драйвер", "драйвер ъпдейт"):
            return IntentMetadata("drivers.check_updates", "check_driver_updates", ADMIN)
        if self._contains_any(text, "windows update", "ъпдейт", "update", "актуализации"):
            return IntentMetadata("system.windows_update", "check_windows_updates", ADMIN)
        if self._contains_any(text, "windows settings", "настройки на windows", "настройките"):
            return IntentMetadata("system.open_settings", "open_windows_update", SAFE)
        if self._contains_any(text, "nvidia", "нвидиа"):
            return IntentMetadata("drivers.nvidia", "nvidia_driver_info", SAFE)
        if self._extract_driver_category(text):
            return IntentMetadata("drivers.info", "driver_info", SAFE)
        if self._contains_any(text, "temperature", "temperatures", "температура", "температури", "cpu temp", "gpu temp"):
            return IntentMetadata("monitoring.temperatures", "system_temperatures", SAFE)
        if self._contains_any(text, "nitrosense", "nitro sense", "нитросенс", "нитро сенс"):
            return IntentMetadata("nitrosense.open_or_support", "nitrosense", SAFE)
        if self._extract_create_target(text):
            return IntentMetadata("files.create", "create_file_or_folder", SAFE)
        if self._extract_adaptive_workflow_goal(text):
            return IntentMetadata("llm.adaptive_workflow", "adaptive_agent", SAFE)
        if self._is_knowledge_question(text):
            return IntentMetadata("knowledge.web_answer", "answer_with_web_search", SAFE)
        if not self._looks_like_unsupported_action(text):
            return IntentMetadata("conversation.chat", "answer_conversation", SAFE)
        return IntentMetadata("unknown", "unknown", SAFE)

    @staticmethod
    def _normalize(text: str) -> str:
        cleaned = text.strip().lower()
        cleaned = re.sub(r"\s+(?:dot|точка)\s+", ".", cleaned)
        cleaned = re.sub(r"[,;]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        for wake_word in WAKE_WORDS:
            if cleaned.startswith(wake_word):
                cleaned = cleaned[len(wake_word) :].strip()
                break
        return cleaned

    @staticmethod
    def _extract_user_preference_set(text: str) -> tuple[str, object] | None:
        patterns: tuple[tuple[str, str], ...] = (
            (r"^(?:call me|address me as|my name is|наричай ме|казвай ми|името ми е)\s+(.+)$", "address_name"),
            (
                r"^(?:preferred browser is|set preferred browser to|favorite browser is|любимият ми браузър е|любимия ми браузър е|предпочитаният ми браузър е|предпочитания ми браузър е|предпочитан браузър)\s+(.+)$",
                "preferred_browser",
            ),
            (
                r"^(?:preferred volume is|set preferred volume to|любимият ми звук е|любимия ми звук е|предпочитаният ми звук е|предпочитания ми звук е|предпочитан звук)\s*(\d{1,3})%?$",
                "preferred_volume",
            ),
        )
        for pattern, key in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            value = match.group(1).strip()
            if not value:
                return None
            if key == "preferred_volume":
                return (key, int(value))
            return (key, value)
        return None

    @staticmethod
    def _is_user_preferences_request(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "show preferences",
                "what are my preferences",
                "what do you call me",
                "what is my preferred browser",
                "покажи предпочитания",
                "какви са ми предпочитанията",
                "как ме наричаш",
                "какъв ми е любимият браузър",
                "какъв ми е любимия браузър",
            )
        )

    @staticmethod
    def _is_voice_diagnostics_request(text: str) -> bool:
        return CommandRouter._contains_any(
            text,
            "voice doctor",
            "voice diagnostics",
            "diagnose voice",
            "speaker diagnostics",
            "speaker test",
            "test voice",
            "why are you not speaking",
            "why don't you speak",
            "no voice",
            "защо не говориш",
            "няма глас",
            "не говориш",
            "диагностика на гласа",
            "провери гласа",
            "провери микрофона",
            "провери говорителя",
            "тествай гласа",
        )

    @staticmethod
    def _is_apply_preferred_volume_request(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "set preferred volume",
                "apply preferred volume",
                "use preferred volume",
                "сложи предпочитания звук",
                "сложи предпочитания ми звук",
                "направи звука предпочитан",
                "направи звука любимия",
                "сложи любимия ми звук",
            )
        )

    @staticmethod
    def _extract_open_target(text: str) -> str | None:
        patterns = (
            r"^(?:open|start|launch)\s+(?:site|website|page\s+)?(.+)$",
            r"^(?:отвори|стартирай|пусни)\s+(?:сайта|сайт|страницата\s+)?(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_remember_text(text: str) -> str | None:
        patterns = (
            r"^(?:remember this|remember)\s+(.+)$",
            r"^(?:запомни това|запомни)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                remembered = match.group(1).strip()
                return remembered or None
        return None

    @staticmethod
    def _extract_categorized_remember(text: str) -> tuple[str, str, int] | None:
        patterns = (
            r"^(?:remember as|remember this as)\s+([a-zа-я_]+)\s*[:\-]?\s+(.+)$",
            r"^(?:запомни като|запомни това като)\s+([a-zа-я_]+)\s*[:\-]?\s+(.+)$",
            r"^(?:remember|запомни)\s+(.+?)\s+(?:as category|като категория)\s+([a-zа-я_]+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            first = match.group(1).strip()
            second = match.group(2).strip()
            if pattern.endswith(r"([a-zа-я_ -]+)$"):
                content, category = first, second
            else:
                category, content = first, second
            if content and category:
                return (content, category, 3)
        return None

    @staticmethod
    def _extract_memory_update(text: str) -> tuple[int, str] | None:
        patterns = (
            r"^(?:update memory|edit memory|change memory)\s+#?(\d+)\s+(?:to|as)\s+(.+)$",
            r"^(?:промени памет|редактирай памет|обнови памет)\s+#?(\d+)\s+(?:на|като)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                return (int(match.group(1)), match.group(2).strip())
        return None

    @staticmethod
    def _extract_memory_category_update(text: str) -> tuple[int, str] | None:
        patterns = (
            r"^(?:set memory|move memory)\s+#?(\d+)\s+(?:category|to category)\s+([a-zа-я_]+)$",
            r"^(?:сложи памет|премести памет)\s+#?(\d+)\s+(?:в категория|категория)\s+([a-zа-я_]+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                return (int(match.group(1)), match.group(2).strip())
        return None

    @staticmethod
    def _is_memory_categories_request(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "memory categories",
                "list memory categories",
                "покажи категории памет",
                "покажи memory categories",
                "какви категории памет",
            )
        )

    @staticmethod
    def _extract_forget_query(text: str) -> str | None:
        patterns = (
            r"^(?:forget this|forget about|forget)\s+(.+)$",
            r"^(?:забрави това|забрави за|забрави)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                query = match.group(1).strip()
                return query or None
        return None

    @staticmethod
    def _extract_memory_query(text: str) -> str | None:
        patterns = (
            r"^(?:what do you remember|what do you remember about me|show memory|search memory)(?:\s+(.+))?$",
            r"^(?:какво помниш|какво помниш за мен|покажи паметта|търси в паметта)(?:\s+(.+))?$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                return (match.group(1) or "").strip()
        return None

    @staticmethod
    def _is_episode_summary_request(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "summarize conversation",
                "summarize this conversation",
                "create episode summary",
                "обобщи разговора",
                "обобщи тази сесия",
                "направи summary на разговора",
                "направи резюме на разговора",
            )
        )

    @staticmethod
    def _extract_episode_memory_query(text: str) -> str | None:
        patterns = (
            r"^(?:show episode memory|show episodic memory|search episode memory)(?:\s+(.+))?$",
            r"^(?:покажи епизодична памет|покажи спомените от разговорите|какво помниш от разговорите|търси в епизодичната памет)(?:\s+(.+))?$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                return (match.group(1) or "").strip()
        return None

    @staticmethod
    def _extract_semantic_memory_query(text: str) -> str | None:
        patterns = (
            r"^(?:semantic memory search|search semantic memory|find in memory|semantic search memory)\s+(.+)$",
            r"^(?:търси семантично в паметта|търси по смисъл в паметта|намери в паметта)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_action_episode_minutes(text: str) -> int | None:
        if not any(
            phrase in text
            for phrase in (
                "summarize actions",
                "summarize action history",
                "summarize commands",
                "create action episode",
                "обобщи действията",
                "обобщи командите",
                "обобщи последните команди",
                "направи резюме на действията",
            )
        ):
            return None
        match = re.search(r"(?:last|последните|за)\s+(\d{1,4})\s*(?:minutes|minute|минути|минута)", text)
        if match:
            return max(1, min(1440, int(match.group(1))))
        return 60

    @staticmethod
    def _extract_action_history_minutes(text: str) -> int | None:
        if not any(
            phrase in text
            for phrase in (
                "what did you do",
                "what have you done",
                "action history",
                "command history",
                "какво направи",
                "какво си направил",
                "какви команди",
                "история на командите",
            )
        ):
            return None
        match = re.search(r"(?:last|последните|за)\s+(\d{1,3})\s*(?:minutes|minute|минути|минута)", text)
        if match:
            return max(1, min(240, int(match.group(1))))
        return 10

    @staticmethod
    def _extract_trace_filter(text: str) -> dict[str, object] | None:
        if not any(phrase in text for phrase in ("trace", "traces", "developer trace", "филтрирай trace", "error", "errors", "грешки")):
            return None
        if any(phrase in text for phrase in ("latest trace", "last trace", "последния trace", "последният trace")):
            return None

        filters: dict[str, object] = {"minutes": 24 * 60, "limit": 20}
        key_patterns = {
            "action": r"(?:action|tool|действие|инструмент)\s+([a-zа-я0-9_.:-]+)",
            "intent": r"(?:intent|намерение)\s+([a-zа-я0-9_.:-]+)",
            "source": r"(?:source|източник)\s+([a-zа-я0-9_.:-]+)",
            "permission": r"(?:permission|права|ниво)\s+([a-zа-я0-9_.:-]+)",
            "error_type": r"(?:error_type|error type|тип грешка|тип на грешка)\s+([a-zа-я0-9_.:-]+)",
            "recommended_action": r"(?:recommended_action|recommended action|препоръчано действие)\s+([a-zа-я0-9_.:-]+)",
        }
        for key, pattern in key_patterns.items():
            match = re.search(pattern, text)
            if match:
                filters[key] = match.group(1).strip()

        if "error_type" not in filters:
            error_shortcuts = {
                "blocked_action": ("blocked error", "blocked errors", "блокирани грешки", "blocked_action"),
                "missing_argument": ("missing argument", "липсващ аргумент", "missing_argument"),
                "unexpected_argument": ("unexpected argument", "неочакван аргумент", "unexpected_argument"),
                "configuration_missing": ("configuration missing", "missing configuration", "липсваща конфигурация", "configuration_missing"),
                "transient_external_failure": ("transient", "temporary failure", "network error", "transient_external_failure"),
                "not_found": ("not found", "не е намерено", "not_found"),
            }
            for error_type, phrases in error_shortcuts.items():
                if any(phrase in text for phrase in phrases):
                    filters["error_type"] = error_type
                    break

        if any(word in text for word in ("failed", "fail", "error", "грешни", "неуспешни", "провалени")):
            filters["ok"] = False
        elif any(word in text for word in ("successful", "success", "ok", "успешни")):
            filters["ok"] = True

        minutes_match = re.search(r"(?:last|последните|за)\s+(\d{1,4})\s*(?:minutes|minute|минути|минута)", text)
        if minutes_match:
            filters["minutes"] = max(1, min(7 * 24 * 60, int(minutes_match.group(1))))

        limit_match = re.search(r"(?:limit|лимит|последни)\s+(\d{1,3})", text)
        if limit_match:
            filters["limit"] = max(1, min(100, int(limit_match.group(1))))

        meaningful_keys = {"source", "intent", "action", "permission", "ok", "error_type", "recommended_action"}
        return filters if any(key in filters for key in meaningful_keys) else None

    @staticmethod
    def _extract_read_ordinal(text: str) -> int | None:
        if not any(word in text for word in ("read", "extract", "прочети", "извлечи")):
            return None
        ordinals = {
            "first": 1,
            "1": 1,
            "първия": 1,
            "първият": 1,
            "първата": 1,
            "първо": 1,
            "second": 2,
            "2": 2,
            "втория": 2,
            "вторият": 2,
            "втората": 2,
            "third": 3,
            "3": 3,
            "третия": 3,
            "третият": 3,
            "третата": 3,
        }
        for word, value in ordinals.items():
            if re.search(rf"\b{re.escape(word)}\b", text):
                return value
        return None

    @staticmethod
    def _extract_read_matching_query(text: str) -> str | None:
        patterns = (
            r"^(?:read|extract)\s+(?:the\s+)?(?:result|source|saved result)\s+(?:for|about|matching)\s+(.+)$",
            r"^(?:прочети|извлечи)\s+(?:резултата|източника|запазения резултат)\s+(?:за|относно|с)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                query = match.group(1).strip()
                return query or None
        return None

    @staticmethod
    def _extract_open_matching_query(text: str) -> str | None:
        patterns = (
            r"^(?:open|launch)\s+(?:the\s+)?(?:result|source|saved result)\s+(?:for|about|matching)\s+(.+)$",
            r"^(?:отвори|пусни)\s+(?:резултата|източника|запазения резултат)\s+(?:за|относно|с)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                query = match.group(1).strip()
                return query or None
        return None

    @staticmethod
    def _is_browser_session_request(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "browser session",
                "show browser session",
                "show browser context",
                "what did you find in browser",
                "what did you read",
                "покажи browser session",
                "покажи браузър сесия",
                "покажи резултатите в браузъра",
                "какво намери в браузъра",
                "какво прочете",
            )
        )

    @staticmethod
    def _is_browser_session_compare_request(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "compare these results",
                "compare saved results",
                "compare read pages",
                "compare these pages",
                "сравни тези резултати",
                "сравни запазените резултати",
                "сравни прочетените",
                "сравни страниците",
                "сравни тези страници",
            )
        )

    @staticmethod
    def _extract_browser_session_question(text: str) -> str | None:
        patterns = (
            r"^(?:answer from browser session|answer from the read pages|answer from what you read)\s+(.+)$",
            r"^(?:what do the read pages say about|what do these pages say about)\s+(.+)$",
            r"^(?:отговори от прочетеното|отговори от страниците|кажи от прочетеното)\s+(.+)$",
            r"^(?:какво казват прочетените страници за|какво казват страниците за|какво пише в прочетеното за)\s+(.+)$",
            r"^(?:обясни прочетеното за|обясни от прочетеното)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                question = match.group(1).strip()
                return question or None
        return None

    @staticmethod
    def _extract_read_url(text: str) -> str | None:
        patterns = (
            r"^(?:read|extract|read webpage|read page)\s+(.+)$",
            r"^(?:прочети|извлечи)\s+(?:страницата|страница|сайта|сайт)?\s*(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            target = match.group(1).strip()
            if target and ("." in target or ":" in target or target.startswith(("http://", "https://"))):
                return target
        return None

    @staticmethod
    def _extract_adaptive_workflow_goal(text: str) -> str | None:
        patterns = (
            r"^(?:agent mode|adaptive mode|run adaptive workflow|сам реши стъпките|адаптивно)\s+(.+)$",
            r"^(?:действай като агент|работи като агент)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, re.I)
            if match:
                goal = match.group(1).strip()
                return goal or None
        return None

    @staticmethod
    def _looks_like_workflow_request(text: str) -> bool:
        if any(phrase in text for phrase in ("workflow", "работен поток", "план от стъпки")):
            return True
        has_connector = any(connector in text for connector in (" и ", " после ", " след това ", " and ", " then "))
        if not has_connector:
            return False
        workflow_verbs = (
            "провери",
            "проучи",
            "намери",
            "сравни",
            "отвори",
            "запомни",
            "направи",
            "потърси",
            "check",
            "research",
            "find",
            "compare",
            "open",
            "remember",
            "make",
            "search",
        )
        return sum(1 for verb in workflow_verbs if verb in text) >= 2

    @staticmethod
    def _is_trace_request(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "developer trace",
                "latest trace",
                "last trace",
                "show trace",
                "покажи trace",
                "покажи трейса",
                "последния trace",
                "последния трейс",
                "защо направи това",
                "как го разбра",
            )
        )

    @staticmethod
    def _extract_site_search(target: str) -> tuple[str, str] | None:
        patterns = (
            r"^(.+?)\s+(?:in|at)\s+([a-zа-я0-9 ._-]+)$",
            r"^(.+?)\s+(?:в|от)\s+([a-zа-я0-9 ._-]+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, target)
            if match:
                query = match.group(1).strip()
                site = match.group(2).strip()
                if query and site:
                    return query, site
        return None

    @staticmethod
    def _extract_deals_query(text: str) -> str | None:
        if not any(word in text for word in ("намаления", "промоции", "оферти", "deals", "discounts", "sales")):
            return None
        cleaned = re.sub(
            r"^(?:къде има|в кои магазини има|потърси|намери|show|find|where are)\s+",
            "",
            text,
        ).strip()
        cleaned = re.sub(r"\b(?:намаления|промоции|оферти|deals|discounts|sales)\b", " ", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    @staticmethod
    def _extract_research_query(text: str) -> str | None:
        blocked_action_words = (
            "windows update",
            "ъпдейт",
            "update",
            "температура",
            "температури",
            "temperature",
            "driver",
            "drivers",
            "драйвер",
            "драйвери",
            "nitrosense",
            "нитросенс",
            "bluetooth",
            "блутут",
            "internet off",
            "internet on",
            "спри интернета",
            "пусни интернета",
        )
        research_patterns = (
            r"^(?:research|deep research|look up)\s+(.+)$",
            r"^(?:проучи|провери в интернет|потърси информация за|потърси в интернет)\s+(.+)$",
            r"^(?:compare|сравни)\s+(.+)$",
        )
        for pattern in research_patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            query = match.group(1).strip()
            if not query or any(word in query for word in blocked_action_words):
                return None
            return query
        return None

    @staticmethod
    def _extract_browser_search_and_open(text: str) -> tuple[str, int] | None:
        patterns = (
            r"^(?:browser search|search browser|search the web|search)\s+(.+?)\s+(?:and\s+)?(?:open|launch)\s+(.+)$",
            r"^(?:търси в браузъра|потърси в браузъра|търси в web|търси в уеб|потърси)\s+(.+?)\s+(?:и\s+)?(?:отвори|пусни)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if not match:
                continue
            query = match.group(1).strip()
            ordinal = CommandRouter._ordinal_from_text(match.group(2))
            if query and ordinal is not None:
                return (query, ordinal)
        return None

    @staticmethod
    def _extract_browser_search_query(text: str) -> str | None:
        patterns = (
            r"^(?:browser search|search browser|search the web)\s+(.+)$",
            r"^(?:търси в браузъра|потърси в браузъра|търси в web|търси в уеб)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                query = match.group(1).strip()
                return query or None
        return None

    @staticmethod
    def _is_browser_automation_status_request(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "browser automation status",
                "playwright status",
                "провери browser automation",
                "провери playwright",
                "има ли playwright",
            )
        )

    @staticmethod
    def _is_screen_vision_status_request(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "screen vision status",
                "screenshot status",
                "провери screen vision",
                "провери screenshot",
                "можеш ли да виждаш екрана",
            )
        )

    @staticmethod
    def _extract_screen_vision_prompt(text: str) -> str | None:
        direct_phrases = (
            "what is on my screen",
            "what am i looking at",
            "describe my screen",
            "read my screen",
            "какво има на екрана",
            "какво гледам",
            "опиши екрана",
            "прочети екрана",
        )
        if any(phrase in text for phrase in direct_phrases):
            return text
        patterns = (
            r"^(?:why is this error|why am i getting this error|explain this screen)\s*(.*)$",
            r"^(?:защо ми дава тази грешка|обясни тази грешка|обясни този екран)\s*(.*)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                return text
        return None

    @staticmethod
    def _ordinal_from_text(text: str) -> int | None:
        ordinals = {
            "first": 1,
            "1": 1,
            "първия": 1,
            "първият": 1,
            "първата": 1,
            "първо": 1,
            "second": 2,
            "2": 2,
            "втория": 2,
            "вторият": 2,
            "втората": 2,
            "third": 3,
            "3": 3,
            "третия": 3,
            "третият": 3,
            "третата": 3,
        }
        for word, value in ordinals.items():
            if re.search(rf"\b{re.escape(word)}\b", text):
                return value
        return None

    @staticmethod
    def _extract_open_first_deal_workflow(text: str) -> str | None:
        if not any(word in text for word in ("намаления", "промоции", "оферти", "deals", "discounts", "sales")):
            return None
        if not any(word in text for word in ("отвори", "open")):
            return None
        if not any(word in text for word in ("първия", "първата", "първо", "first", "1")):
            return None
        patterns = (
            r"^(?:намери|потърси|провери)\s+(?:намаления|промоции|оферти)\s+(?:за\s+)?(.+?)\s+(?:и\s+)?(?:отвори|пусни).*$",
            r"^(?:find|search|check)\s+(?:deals|discounts|sales)\s+(?:for\s+)?(.+?)\s+(?:and\s+)?open.*$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                query = match.group(1).strip()
                return query or None
        return None

    @staticmethod
    def _extract_open_ordinal(text: str) -> int | None:
        if not any(word in text for word in ("open", "отвори", "пусни")):
            return None
        ordinals = {
            "first": 1,
            "1": 1,
            "първия": 1,
            "първият": 1,
            "първо": 1,
            "second": 2,
            "2": 2,
            "втория": 2,
            "вторият": 2,
            "third": 3,
            "3": 3,
            "третия": 3,
            "третият": 3,
        }
        for word, value in ordinals.items():
            if re.search(rf"\b{re.escape(word)}\b", text):
                return value
        return None

    @staticmethod
    def _extract_volume_percent(text: str) -> int | None:
        if not any(word in text for word in ("volume", "звук", "звука")):
            return None
        match = re.search(r"\b(?:to|на|до)\s*(\d{1,3})\b|\b(\d{1,3})\s*%", text)
        if not match:
            return None
        value = int(match.group(1) or match.group(2))
        return max(0, min(100, value))

    @staticmethod
    def _extract_driver_category(text: str) -> str | None:
        if not any(word in text for word in ("driver", "drivers", "драйвер", "драйвери")):
            return None
        if any(word in text for word in ("chipset", "чипсет")):
            return "chipset"
        if any(word in text for word in ("video", "gpu", "display", "видео", "видеокарта", "видео карта")):
            return "display"
        if any(word in text for word in ("audio", "sound", "аудио", "звук")):
            return "audio"
        if any(word in text for word in ("network", "wifi", "wi-fi", "internet", "мреж", "интернет")):
            return "network"
        if any(word in text for word in ("bluetooth", "блутут")):
            return "bluetooth"
        if any(word in text for word in ("all", "всички")):
            return "all"
        return "all"

    @staticmethod
    def _extract_create_target(text: str) -> tuple[str, str] | None:
        folder_match = re.match(r"^(?:create|make|направи|създай)\s+(?:folder|directory|папка|папката)\s+(.+)$", text)
        if folder_match:
            return ("folder", folder_match.group(1).strip())
        file_match = re.match(r"^(?:create|make|направи|създай)\s+(?:file|document|файл|документ)\s+(.+)$", text)
        if file_match:
            return ("file", file_match.group(1).strip())
        return None

    @staticmethod
    def _extract_mode(text: str) -> str | None:
        if any(phrase in text for phrase in ("режим игра", "game mode", "gaming mode", "gaming")):
            return "gaming"
        if any(phrase in text for phrase in ("quiet mode", "тих режим", "режим тихо", "quiet")):
            return "quiet"
        if any(phrase in text for phrase in ("study mode", "режим учене", "учене", "study")):
            return "study"
        if any(phrase in text for phrase in ("battery saver", "battery mode", "режим батерия", "пести батерия", "батерия")):
            return "battery"
        return None

    @staticmethod
    def _extract_docx_topic(text: str) -> str | None:
        patterns = (
            r"^(?:make|create|write)\s+(?:me\s+)?(?:a\s+)?(?:docx|word document|document)\s+(?:about|for)\s+(.+)$",
            r"^(?:направи|създай|напиши)\s+(?:ми\s+)?(?:docx|word документ|документ)\s+(?:за|относно)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.match(pattern, text)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_temperature_threshold(text: str) -> int | None:
        if not any(word in text for word in ("temperature", "температура", "температури")):
            return None
        if not any(word in text for word in ("warning", "warn", "предупреди", "предупреждение", "над")):
            return None
        match = re.search(r"\b(?:above|over|над)\s*(\d{2,3})\b|\b(\d{2,3})\s*(?:c|градуса)?", text)
        if match:
            return int(match.group(1) or match.group(2))
        return 85

    @staticmethod
    def _is_knowledge_question(text: str) -> bool:
        starters = (
            "what is",
            "what happened",
            "who is",
            "when did",
            "why",
            "how",
            "compare",
            "explain",
            "research",
            "какво е",
            "какво се случи",
            "какво е станало",
            "кой е",
            "кога",
            "защо",
            "как",
            "сравни",
            "обясни",
            "разкажи",
            "провери в интернет",
            "потърси",
        )
        return any(text.startswith(starter) for starter in starters)

    @staticmethod
    def _looks_like_unsupported_action(text: str) -> bool:
        action_starters = (
            "open ",
            "start ",
            "launch ",
            "close ",
            "install ",
            "delete ",
            "remove ",
            "move ",
            "copy ",
            "run ",
            "execute ",
            "отвори ",
            "стартирай ",
            "пусни ",
            "затвори ",
            "инсталирай ",
            "изтрий ",
            "премахни ",
            "премести ",
            "копирай ",
            "направи ",
            "създай ",
        )
        return text.startswith(action_starters)

    def _remember_conversation(self, user_text: str, result: CommandResult) -> None:
        if not result.ok or contains_private_content(result.metadata):
            return
        self.conversation_memory.add_turn("user", redact_sensitive_text(user_text).text)
        self.conversation_memory.add_turn("assistant", redact_sensitive_text(result.message).text)
        if getattr(self.actions, "dry_run", False):
            return
        try:
            self.episodic_memory.summarize_conversation(
                self.conversation_memory.recent(limit=80),
                ai=self.ai,
                force=False,
            )
        except Exception:
            pass

    @staticmethod
    def _contains_any(text: str, *needles: str) -> bool:
        return any(needle in text for needle in needles)

    @staticmethod
    def _is_affirmative_reply(text: str) -> bool:
        return text.strip() in {
            "yes",
            "y",
            "yeah",
            "yep",
            "confirm",
            "confirmed",
            "ok",
            "okay",
            "да",
            "дам",
            "добре",
            "потвърждавам",
            "ок",
        }

    @staticmethod
    def _is_negative_reply(text: str) -> bool:
        return text.strip() in {
            "no",
            "n",
            "nope",
            "cancel",
            "stop",
            "abort",
            "не",
            "недей",
            "отмени",
            "спри",
            "отказ",
        }

    @staticmethod
    def _looks_like_url(target: str) -> bool:
        return "." in target and " " not in target

    @staticmethod
    def _target_to_domain(target: str) -> str | None:
        parts = target.split()
        if len(parts) == 2 and parts[1] in {"bg", "com", "net", "org", "eu", "io", "dev"}:
            return f"{parts[0]}.{parts[1]}"
        return None


def _setting_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "не", "изключено"}
    return bool(value)


def _matching_sentences(text: str, tokens: list[str]) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]
    if not sentences:
        return []
    ranked: list[tuple[int, str]] = []
    for sentence in sentences:
        haystack = sentence.lower()
        score = sum(1 for token in tokens if token in haystack)
        if score > 0:
            ranked.append((score, sentence))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [sentence for _score, sentence in ranked]
