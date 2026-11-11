from __future__ import annotations

from jarvis.ai_client import JarvisAI
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.tool_registry import build_core_tool_registry
from jarvis.web_context import WebContext
from jarvis.windows_actions import WindowsActions
from jarvis.workflows import WorkflowRunner


def make_router(tmp_path) -> CommandRouter:
    router = CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=True),
        ai=JarvisAI(dry_run=True),
    )
    router.web_context = WebContext(path=tmp_path / "web_context.json")
    router.tools = build_core_tool_registry(
        router.actions,
        router.ai,
        memory=router.long_term_memory,
        audit=router.audit_reader,
        web_context=router.web_context,
    )
    router.workflow_runner = WorkflowRunner(router.tools)
    return router


def test_router_open_first_deal_workflow(tmp_path):
    router = make_router(tmp_path)

    result = router.handle("jarvis намери оферти за гейминг мишки и отвори първия")

    assert result.ok
    assert result.intent == "workflow.open_first_deal"
    assert result.metadata["workflow"] == "open_first_deal"
    assert [step["tool"] for step in result.metadata["workflow_steps"]] == ["save_deal_candidates", "open_url"]
    assert router.web_context.pick(1) is not None
