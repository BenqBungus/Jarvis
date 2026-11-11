"""Explicit user preauthorization, never a general permission bypass."""

TRUSTED_LOCAL_TOOLS = frozenset({
    "create_folder", "create_file", "create_text_file", "create_local_folder",
    "create_local_file", "rename_local_path", "move_local_path", "copy_local_file",
    "create_zip", "extract_zip", "recycle_local_path", "close_app", "end_process",
    "save_file_edit", "close_folder_window",
})


# False while a Kid or Guest profile is active (permission_levels.py): full
# access then never skips a confirmation, whatever Settings say.
_full_access_allowed = True


def allow_full_access(allowed: bool) -> None:
    global _full_access_allowed
    _full_access_allowed = bool(allowed)


def trusted_local_action(settings, action_name: str) -> bool:
    if not _full_access_allowed or settings is None or settings.safety.get("full_access_local") is not True:
        return False
    for prefix in ("Run Jarvis tool: ", "Run adaptive workflow step: ", "Run workflow step: "):
        if action_name.startswith(prefix):
            action_name = action_name[len(prefix):]
            break
    return action_name in TRUSTED_LOCAL_TOOLS
