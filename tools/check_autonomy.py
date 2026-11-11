"""Read-only live agent/browser check. No microphone or personal browser profile."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jarvis.ai_client import JarvisAI
from jarvis.browser.managed import ManagedBrowser
from jarvis.browser.tools import register_managed_browser_tools
from jarvis.config import ensure_openai_api_key_visible
from jarvis.tool_registry import ToolRegistry
from jarvis.user_settings import JarvisSettings
from jarvis.windows_actions import WindowsActions
from jarvis.workflows import WorkflowRunner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-api", action="store_true", help="Make bounded paid OpenAI requests")
    parser.add_argument("--opera", action="store_true", help="Test the configured preferred browser executable")
    args = parser.parse_args()
    settings = JarvisSettings.load()
    actions = WindowsActions(settings=settings)
    executable = actions._preferred_browser_command() if args.opera else None
    workspace = Path(__file__).resolve().parents[1]
    browser = ManagedBrowser(workspace=workspace, headless=True, executable_path=executable)

    class Controller:
        def managed_call(self, operation, **arguments):
            return browser.call(operation, **arguments)

    try:
        if args.live_api:
            ensure_openai_api_key_visible()
            available = ToolRegistry()
            register_managed_browser_tools(available, Controller())
            registry = ToolRegistry()
            for name in ("browser_navigate", "browser_inspect", "browser_tabs"):
                registered = available.get(name)
                registry.register(registered.spec, registered.handler)
            ai = JarvisAI(settings=settings)
            goal = "Open https://example.com, read its heading, and report the heading. Do nothing else."
            runner = WorkflowRunner(registry)
            runner.on_progress = print
            result = runner.run_adaptive("diagnostic", goal,
                decide_next=lambda steps: ai.decide_next_workflow_step(goal, registry, steps),
                max_steps=4, max_seconds=120)
        else:
            result = browser.call("navigate", url="https://example.com")
        print(result.message)
        output = workspace / "data/diagnostics"
        output.mkdir(parents=True, exist_ok=True)
        (output / "autonomy-check.json").write_text(json.dumps({
            "ok": result.ok, "message": result.message, "metadata": result.metadata,
            "live_api": args.live_api, "preferred_browser": args.opera}, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.ok and browser._pool:
            browser._pool.submit(lambda: browser._page().screenshot(
                path=str(output / "managed-browser.png"))).result()
        if not result.ok:
            raise SystemExit(1)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
