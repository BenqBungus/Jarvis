from __future__ import annotations


class SafetyPolicy:
    def __init__(self, auto_confirm: bool = False) -> None:
        self.auto_confirm = auto_confirm
        self.settings = None

    def confirm(self, action_name: str, reason: str) -> bool:
        from .trusted_actions import trusted_local_action
        if trusted_local_action(self.settings, action_name):
            return True
        if self.auto_confirm:
            return True

        print(f"High-impact action: {action_name}")
        print(reason)
        try:
            answer = input("Type YES to continue: ").strip()
        except EOFError:
            return False
        return answer == "YES"
