"""Deterministic Gmail routes, excluded from the offline-only command service."""
import re
from .models import CommandResult

_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
             "първия": 1, "втория": 2, "третия": 3, "четвъртия": 4, "петия": 5}


def gmail_command(text, execute):
    dispatch = execute

    def execute(name, arguments=None):
        result = dispatch(name, arguments)
        return result.with_metadata(metadata={**result.metadata, "private_content": True})

    text = text.strip()
    key = text.casefold().rstrip("?.!")
    simple = {"gmail status": "gmail_status", "статус на gmail": "gmail_status",
              "disconnect gmail": "gmail_disconnect", "изключи gmail": "gmail_disconnect"}
    if key in simple:
        return execute(simple[key])
    followups = {"what should i do about this email", "what should i do about that email",
                 "recommend what to do about this email", "analyze this email", "analyse this email",
                 "какво да направя с този имейл", "анализирай този имейл"}
    if key in followups:
        current = execute("gmail_selection")
        if not current.ok:
            return current
        ordinal = current.metadata.get("last_read_ordinal")
        if type(ordinal) is not int:
            return CommandResult(False, "Choose an email number first, for example: analyze email 1.",
                                 metadata={"private_content": True})
        return execute("gmail_advise", {"selection_id": current.metadata["selection_id"], "ordinal": ordinal})
    if key in {"check gmail", "check my email", "check my emails", "gmail inbox", "провери gmail", "провери пощата"}:
        return execute("gmail_search", {"query": "in:inbox"})
    if key in {"unread emails", "unread gmail", "show unread emails", "check my unread emails", "непрочетени имейли"}:
        return execute("gmail_search", {"query": "in:inbox is:unread"})
    match = re.fullmatch(r"(?:search gmail(?: for)?|търси в gmail)\s+(.+)", text, re.I)
    if match:
        return execute("gmail_search", {"query": match[1]})
    action = r"(read(?: aloud)?|summarize|summarise|analyze|analyse|advise on|what should i do about|прочети|обобщи|анализирай)"
    match = re.fullmatch(action + r"\s+(?:gmail\s+)?(?:email|message|имейл|писмо)\s+(\d+)[.?!]?", text, re.I)
    if not match:
        match = re.fullmatch(action + r"\s+(?:the\s+)?(" + "|".join(_ORDINALS) + r")\s+(?:email|message|имейл|писмо)[.?!]?", text, re.I)
    if match:
        current = execute("gmail_selection")
        if not current.ok:
            return current
        verb = match[1].casefold()
        tool = ("gmail_read" if verb in {"read", "read aloud", "прочети"} else
                "gmail_summarize" if verb in {"summarize", "summarise", "обобщи"} else "gmail_advise")
        return execute(tool,
                       {"selection_id": current.metadata["selection_id"],
                        "ordinal": int(match[2]) if match[2].isdigit() else _ORDINALS[match[2].casefold()]})
    return None
