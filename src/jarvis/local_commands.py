from __future__ import annotations

import re
import shlex
from decimal import Decimal, InvalidOperation

from .config import APP_ALIASES, WAKE_WORDS
from .models import CommandResult
from .local_file_actions import LocalFileActions
from .rollback import RollbackManager
from .tool_registry import ToolCall

_RESULT_NUMBERS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                   "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                   "първи": 1, "първия": 1, "втори": 2, "втория": 2, "трети": 3, "третия": 3}


class LocalCommandService:
    """No AI, web, or speech dependency. Unknown input never falls through to cloud routing."""

    def __init__(self, actions, settings, files, tools, safety) -> None:
        self.actions, self.settings, self.files = actions, settings, files
        self.tools, self.safety = tools, safety

    def handle(self, raw: str) -> CommandResult:
        result = self._handle(raw)
        return result.with_metadata(metadata={**result.metadata, "local_only": True})

    def _execute(self, name: str, arguments: dict | None = None, *, detail: str = "") -> CommandResult:
        registered = self.tools.get(name)
        if registered is None:
            return CommandResult(False, "Local tool is unavailable.")
        spec = registered.spec
        if spec.permission == "blocked":
            return CommandResult(False, "Local tool is blocked.", permission="blocked")
        approved = None
        if spec.permission in {"confirm", "admin"} or spec.requires_confirmation:
            approved = self.safety.confirm(spec.name, f"{spec.description} {detail} Arguments: {arguments or {}}")
            if not approved:
                return CommandResult(False, "Local action cancelled.", permission=spec.permission,
                                     requires_confirmation=True, confirmed=False)
        result = self.tools.execute(ToolCall(name, arguments or {}))
        from .trusted_actions import trusted_local_action
        if approved and trusted_local_action(self.settings, name):
            result = result.with_metadata(metadata={**result.metadata, "approval_source": "trusted_local_setting"})
        return result.with_metadata(requires_confirmation=True, confirmed=True) if approved else result

    def resource_command(self, text: str) -> CommandResult | None:
        """Shared deterministic routes for voice fallback and offline commands."""
        text = text.strip()
        inspect_path = re.fullmatch(r'(?:inspect path|check path|file info|folder info|провери път|информация за файл|информация за папка)\s+(.+)', text, re.I)
        if inspect_path:
            return self._execute("inspect_local_path", {"path": inspect_path[1].strip().strip('"')})
        folder_close = re.fullmatch(r'(?:close (?:the )?(?:current )?folder(?: window)?|затвори папката)(?:\s+(.+))?[.!]?', text, re.I)
        if folder_close:
            observed = self._execute("list_folder_windows")
            if not observed.ok:
                return observed
            rows = observed.metadata.get("folder_windows", [])
            title = (folder_close[1] or "").strip().strip('"')
            if title:
                rows = [row for row in rows if row["title"].casefold() == title.casefold()]
            elif any(row["foreground"] for row in rows):
                rows = [row for row in rows if row["foreground"]]
            if len(rows) != 1 or observed.metadata.get("partial"):
                return CommandResult(False, "Name one exact folder window to close; no files were deleted.\n" + observed.message,
                                     metadata=observed.metadata)
            return self._execute("close_folder_window", {"selection_id": rows[0]["selection_id"]})
        recycle = re.fullmatch(r'(?:(?:delete|recycle|remove) (?:file|folder)|изтрий (?:файл|папка))\s+(.+)', text, re.I)
        if recycle:
            return self._execute("recycle_local_path", {"path": recycle[1].strip().strip('"')})
        shared_commands = {"start screen sharing": "start_screen_sharing", "share my screen": "start_screen_sharing",
                           "stop screen sharing": "stop_screen_sharing", "screen sharing status": "screen_sharing_status",
                           "preview file edit": "preview_file_edit", "discard file edit": "discard_file_edit",
                           "сподели екрана": "start_screen_sharing", "спри споделянето на екрана": "stop_screen_sharing",
                           "статус на споделянето": "screen_sharing_status", "покажи предложената редакция": "preview_file_edit",
                           "отхвърли редакцията": "discard_file_edit"}
        if text.casefold().rstrip("?.!") in shared_commands:
            return self._execute(shared_commands[text.casefold().rstrip("?.!")])
        screen = re.fullmatch(r"(?:ask screen|въпрос за екрана)\s+(.+)", text, re.I)
        if screen:
            return self._execute("ask_shared_screen", {"question": screen[1]})
        edit = re.fullmatch(r'(?:edit file|редактирай файл)\s+"([^"]+)"\s+(?:to|така че)\s+(.+)', text, re.I)
        if edit:
            return self._execute("propose_file_edit", {"path": edit[1], "instructions": edit[2]})
        save_edit = re.fullmatch(r'(?:save edited copy to|запази редактирано копие в)\s+(.+)', text, re.I)
        if save_edit:
            preview = self._execute("preview_file_edit")
            if not preview.ok:
                return preview
            return self._execute("save_file_edit", {"proposal_id": preview.metadata["proposal_id"], "destination": save_edit[1].strip().strip('"')})
        document = re.fullmatch(r'(?:(?:analyze|analyse|summarize|summarise) document|(?:анализирай|обобщи|прочети) (?:документ|документа))\s+(.+)', text, re.I)
        if document:
            return self._execute("analyze_document", {"path": document[1].strip().strip('"')})
        if text.casefold().rstrip("?.!") in {"document context", "show document context", "what document are we discussing", "кой документ обсъждаме", "покажи контекста на документа"}:
            return self._execute("document_context")
        if text.casefold().rstrip("?.!") in {"forget document", "forget this document", "забрави документа", "забрави този документ"}:
            return self._execute("forget_document")
        question = re.fullmatch(r'(?:ask document|въпрос по документа)\s+(.+)', text, re.I)
        draft = re.fullmatch(r'(?:write document|напиши документ)\s+"([^"]+)"\s+(?:to|в)\s+"([^"]+)"\s+(?:about|за)\s+(.+)', text, re.I)
        if question or draft:
            context = self._execute("document_context")
            if not context.ok:
                return context
            arguments = {"document_id": context.metadata["document_id"]}
            if question:
                return self._execute("ask_document", {**arguments, "question": question[1]})
            return self._execute("draft_document", {**arguments, "title": draft[1], "destination": draft[2], "instructions": draft[3]})
        file_phrase = text.casefold().rstrip("?.!")
        if file_phrase in {"show file results", "list file results", "покажи файловите резултати"}:
            return self._execute("show_file_results")
        choice = (re.fullmatch(r"open (?:the )?file result\s+(\w+)", file_phrase)
                  or re.fullmatch(r"open (?:the )?(\w+) file result", file_phrase)
                  or re.fullmatch(r"отвори (първи(?:я)?|втори(?:я)?|трети(?:я)?|\d{1,2}) (?:файл|файлов резултат)", file_phrase))
        if choice:
            number = int(choice[1]) if choice[1].isdecimal() and len(choice[1]) <= 2 else _RESULT_NUMBERS.get(choice[1])
            if number is None:
                return CommandResult(False, "Specify a numbered file result.")
            observed = self._execute("show_file_results")
            if not observed.ok:
                return observed
            return self._execute("open_file_result", {"ordinal": number, "search_id": observed.metadata["search_id"]})
        if self.files.has_search_context and (
            re.fullmatch(r"open (?:the )?\w+ result", file_phrase)
            or re.fullmatch(r"open (?:the )?result \w+", file_phrase)
            or re.fullmatch(r"отвори \w+(?: резултат)?", file_phrase) and any(word in file_phrase for word in ("първи", "втори", "трети"))
        ):
            return CommandResult(False, "Do you mean a local file result or a web result? Specify the result type; nothing was opened.",
                                 metadata={"clarification_required": True})
        inventory_phrase = text.casefold().rstrip("?.!")
        if inventory_phrase in {"device info", "show device info", "what laptop do i have", "show laptop model",
                                "hardware identity", "show bios version", "what cpu do i have", "what gpu do i have",
                                "какъв лаптоп имам", "покажи модела на лаптопа"}:
            return self._execute("device_info")
        if inventory_phrase in {"show installed drivers", "list installed drivers"}:
            return self._execute("driver_info")
        driver = re.fullmatch(r"(?:show|list) (display|nvidia|chipset|audio|network|bluetooth) drivers?", inventory_phrase)
        if driver:
            return self._execute("nvidia_driver_info") if driver[1] == "nvidia" else self._execute("driver_info", {"category": driver[1]})
        if inventory_phrase == "what is my nvidia driver version":
            return self._execute("nvidia_driver_info")
        search = re.fullmatch(r"(?:find|search) (files?|folders?)(?:\s+(.*))?", text, re.I)
        if search:
            arguments = {"kind": "folder" if search[1].casefold().startswith("folder") else "file"}
            try:
                tokens = shlex.split(search[2] or "", posix=False)
                index, used = 0, set()
                while index < len(tokens):
                    option = tokens[index].casefold()
                    fields = {"named": "query", "matching": "query", "containing": "content", "type": "extension", "in": "root",
                              "after": "modified_after", "before": "modified_before", "min": "min_size_bytes", "max": "max_size_bytes"}
                    field = fields.get(option)
                    if field is None or field in used or index + 1 >= len(tokens):
                        raise ValueError('Use named/matching, containing "literal text", type, in, after/before YYYY-MM-DD, or min/max size.')
                    used.add(field)
                    value = tokens[index + 1].strip('"')
                    index += 2
                    if option == "containing" and not tokens[index - 1].startswith('"'):
                        while index < len(tokens) and tokens[index].casefold() not in fields:
                            value += " " + tokens[index]
                            index += 1
                    if option in {"min", "max"}:
                        size = re.fullmatch(r"(\d+(?:\.\d+)?)(B|KB|MB|GB)?", value, re.I)
                        if not size:
                            raise ValueError("Use a nonnegative size with B, KB, MB or GB.")
                        unit = (size[2] or "B").upper()
                        if not size[2] and index < len(tokens) and tokens[index].upper() in {"B", "KB", "MB", "GB"}:
                            unit = tokens[index].upper()
                            index += 1
                        amount = Decimal(size[1]) * {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3}[unit]
                        if amount != amount.to_integral_value():
                            raise ValueError("Size must resolve to a whole number of bytes.")
                        value = int(amount)
                    arguments[field] = value
                    if option == "matching":
                        arguments["match_mode"] = "fuzzy"
                return self._execute("search_local_files", arguments)
            except (ValueError, InvalidOperation) as exc:
                return CommandResult(False, f"File search: {exc}")
        if text.casefold().rstrip("?.!") in {
            "hardware status", "show hardware status", "system status", "show system status",
            "temp", "usage", "processor usage", "processor temperature", "cpu usage percentage",
            "usage на процесора", "temp на процесора",
            "cpu usage", "gpu usage", "cpu temperature", "gpu temperature", "cpu temp", "gpu temp",
            "temperatures", "check temperatures", "what is my cpu temperature", "what is my gpu temperature",
            "what is my cpu usage", "what is my gpu usage", "how hot is my cpu", "how hot is my gpu",
            "покажи температурите", "провери температурите", "натоварване на процесора", "натоварване на видеокартата",
        }:
            return self._execute("system_hardware_status")
        if text.casefold() in {"undo", "undo last action", "undo the last action", "undo last change",
                               "rollback", "върни последното", "отмени последното"}:
            try:
                latest = RollbackManager().peek()
            except (OSError, ValueError, TypeError, KeyError) as exc:
                return CommandResult(False, f"Undo history could not be read: {exc}")
            if latest is None and not self.actions.dry_run:
                return CommandResult(False, "There is no reversible action to undo.")
            arguments = {"expected_timestamp": latest.timestamp} if latest else {}
            return self._execute("undo_last_action", arguments,
                                 detail=latest.label if latest else "Dry run; nothing will change.").with_metadata(intent="system.undo")
        if text.casefold() in {"open task manager", "task manager", "отвори таск мениджъра"}:
            return self._execute("open_task_manager")
        if text.casefold() in {"list all processes", "show all processes", "show background tasks", "list background tasks"}:
            return self._execute("list_processes", {"include_background": True})
        launch = re.fullmatch(r"(?:launch|start|open) installed app\s+(.+)", text, re.I)
        if launch:
            return self._execute("launch_installed_app", {"query": launch[1].strip()})
        rename = re.fullmatch(r'(?:rename|преименувай)\s+"([^"]+)"\s+(?:to|на)\s+"([^"]+)"', text, re.I)
        if rename:
            return self._execute("rename_local_path", {"path": rename[1], "new_name": rename[2]})
        operation = re.fullmatch(r'(move|copy|zip|unzip|премести|копирай|архивирай|разархивирай)\s+"([^"]+)"\s+(?:to|в)\s+"([^"]+)"', text, re.I)
        if operation:
            tool = {"move": "move_local_path", "copy": "copy_local_file", "zip": "create_zip", "unzip": "extract_zip",
                    "премести": "move_local_path", "копирай": "copy_local_file", "архивирай": "create_zip", "разархивирай": "extract_zip"}[operation[1].casefold()]
            return self._execute(tool, {"source": operation[2], "destination": operation[3]})
        if text.casefold() in {"cancel task", "stop task", "cancel current task", "stop current task",
                               "спри задачата", "отмени задачата"}:
            return self._execute("cancel_task")
        create_text = re.fullmatch(r'(?:(?:create|make|write)\s+(?:a\s+)?text file|(?:създай|напиши|направи)\s+(?:текстов\s+)?файл)\s+(.+?)\s+(?:with content|със съдържание|с текст)\s+(.+)', text, re.I | re.S)
        if create_text:
            target = create_text[1].strip().strip('"')
            if LocalFileActions.explicit_path(target):
                return self._execute("create_local_file", {"path": target, "content": create_text[2]})
            return self._execute("create_text_file", {"target": target, "content": create_text[2]})
        create = re.fullmatch(r"(?:create|make|направи|създай)\s+(?:(?:a|new)\s+)?(folder|directory|file|папка|файл)\s+(?:(?:called|named)\s+)?(.+)", text, re.I)
        if create:
            tool = "create_folder" if create[1].casefold() in {"folder", "directory", "папка"} else "create_file"
            target = create[2].strip().strip('"')
            location = re.fullmatch(r"(.+?)\s+(?:on|in)\s+(?:the\s+)?(Desktop|Documents|Downloads|Pictures)", target, re.I)
            if location:
                target = location[2] + "/" + location[1].strip().strip('"')
            if LocalFileActions.explicit_path(target):
                return self._execute("create_local_folder" if tool == "create_folder" else "create_local_file", {"path": target})
            return self._execute(tool, {"target": target})
        listing = re.fullmatch(r"(?:list|show|покажи)\s+(?:folder|папка)\s+(.+)", text, re.I)
        if listing:
            target = listing[1].strip().strip('"')
            if LocalFileActions.explicit_path(target):
                return self._execute("list_local_folder", {"path": target})
            return self._execute("list_folder", {"target": target})
        processes = re.fullmatch(r"(?:(?:list|show|find) processes|(?:покажи|намери) процеси)(?:\s+(?:(?:for|за)\s+)?(.+))?", text, re.I)
        if processes:
            return self._execute("list_processes", {"query": (processes[1] or "").strip()})
        ending = re.fullmatch(r"(end process|end task|terminate process|force close|close app|close application|quit app|close|quit|приключи процес|спри принудително|затвори приложение|затвори програмата|затвори)\s+(.+)", text, re.I)
        if ending:
            verb = ending[1].casefold()
            tool = "close_app" if verb in {"close app", "close application", "quit app", "close", "quit", "затвори приложение", "затвори програмата", "затвори"} else "end_process"
            query = ending[2].strip().strip('"')
            if tool == "close_app" and re.match(r"^(?:the\s+)?(?:current\s+)?(?:browser\s+)?(?:tabs?|windows?|conversation|call)\b", query, re.I):
                return None  # Browser/call targets belong to their existing intent routes.
            if tool == "close_app" and re.match(r"^(?:таба|табовете|прозореца|разговора|обаждането)\b", query, re.I):
                return None
            observed = self._execute("list_processes", {"query": query})
            if not observed.ok:
                return observed
            rows = [row for row in observed.metadata.get("processes", [])
                    if str(row["pid"]) == query or row["name"].casefold().removesuffix(".exe") == query.casefold().removesuffix(".exe")]
            if tool == "close_app" and rows and not query.isdecimal():
                rows = [row for row in rows if row.get("has_window")]
                if not rows:
                    return CommandResult(False, "No visible window for normal close. The app may be in the tray; nothing was force-stopped.",
                                         metadata=observed.metadata)
            if len(rows) != 1 or observed.metadata.get("partial"):
                return CommandResult(False, "Choose one exact process PID from the list; nothing was stopped.\n" + observed.message,
                                     metadata=observed.metadata)
            row = rows[0]
            if "selection_id" not in row:
                return CommandResult(False, row.get("blocked_reason", "This process is protected."))
            return self._execute(tool, {"selection_id": row["selection_id"]})
        return None

    def _handle(self, raw: str) -> CommandResult:
        text = raw.strip()
        for wake in WAKE_WORDS:
            if text.casefold().startswith(wake + " ") or text.casefold().startswith(wake + ","):
                text = text[len(wake):].lstrip(" ,")
                break
        lower = text.casefold()
        resource = self.resource_command(text)
        if resource is not None:
            return resource
        volume = re.fullmatch(r"(?:звук(?:а|ът)?(?: на)?|(?:направи|сложи|намали|увеличи) звука(?: на)?|volume(?: to)?)\s+(\d{1,3})\s*%?", lower)
        if volume:
            percent = int(volume[1])
            if percent > 100:
                return CommandResult(False, "Звукът трябва да е между 0 и 100.")
            return self._execute("set_volume", {"percent": percent})
        commands = {"температури": "system_temperatures", "провери температурите": "system_temperatures",
                    "temperatures": "system_temperatures", "отвори nitrosense": "open_nitrosense",
                    "open nitrosense": "open_nitrosense", "отвори нитросенс": "open_nitrosense"}
        if lower in commands:
            return self._execute(commands[lower])
        search = re.fullmatch(r"(?:намери|find)\s+(.+?)(?:\s+(?:в|in)\s+(Desktop|Documents|Downloads|Pictures))?", text, re.I)
        if search:
            return self.files.search(search[1], search[2] or "")
        opening = re.fullmatch(r"(?:отвори|open)\s+(.+)", text, re.I)
        if opening:
            target = opening[1].strip().strip('"')
            folders = {"работен плот": "desktop", "документи": "documents", "изтегляния": "downloads", "снимки": "pictures"}
            target = folders.get(target.casefold(), target)
            if target.casefold() in self.files.folders or re.match(r"^[A-Za-z]:[\\/]", target):
                return self.files.open_path(target)
            aliases = {**APP_ALIASES, **self.settings.app_aliases}
            if target.casefold() in aliases:
                return self.actions.open_app(aliases[target.casefold()], target)
        return CommandResult(False, "Неразпозната локална команда. Не е изпратена към AI и не е изпълнено действие.",
                             metadata={"local_only": True})


class TeachingService:
    """Instructions only. This service intentionally has no access to actions or tools."""

    def explain(self, topic: str) -> CommandResult:
        text = topic.casefold()
        if any(word in text for word in ("звук", "volume")):
            steps = ["Отвори Settings > System > Sound.", "Избери правилното изходно устройство.",
                     "Премести Volume до желания процент и провери звука."]
        elif any(word in text for word in ("nitrosense", "нитросенс", "вентилатор", "performance", "охлаждан")):
            steps = ["Отвори NitroSense от Start.", "Провери дали лаптопът е на зарядно и какви режими показва тази версия.",
                     "Ако има Scenario, избери желания режим и провери кой е маркиран като активен.",
                     "За вентилаторите използвай Auto или наличните контроли на Acer. Не изключвай охлаждането.",
                     "Следи температурите; Performance не е решение за прегряване."]
        elif any(word in text for word in ("update", "актуализац", "драйвер", "ъпдейт")):
            steps = ["Отвори Settings > Windows Update.", "Избери Check for updates и прочети списъка, преди да инсталираш.",
                     "За драйвер провери точния модел и текущата версия в Device Manager.",
                     "Използвай официалната Acer или производителска страница. Не инсталирай BIOS автоматично."]
        elif any(word in text for word in ("файл", "папк", "file", "folder")):
            steps = ["Отвори File Explorer и избери папката, в която искаш да работиш.",
                     "Използвай полето за търсене по име и провери пълния път на резултата.",
                     "Отвори документа с познатото приложение. Не стартирай непознати програми или скриптове."]
        else:
            return CommandResult(False, "Още няма локално ръководство за тази тема. Нищо не е изпълнено.",
                                 action="teach_task", metadata={"instruction_only": True, "local_only": True})
        message = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1))
        return CommandResult(True, message, action="teach_task",
                             metadata={"instruction_only": True, "local_only": True, "steps": steps,
                                       "action_executed": False, "screen_observed": False})
