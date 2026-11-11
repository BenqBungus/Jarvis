from __future__ import annotations

from jarvis.ai_client import JarvisAI
from jarvis.tool_registry import ToolRegistry


def test_dry_run_adaptive_workflow_decision_finishes_with_preview():
    decision = JarvisAI(dry_run=True).decide_next_workflow_step(
        "отвори facebook",
        ToolRegistry(),
        previous_steps=[],
    )

    assert decision.ok
    assert decision.action == "finish"
    assert "Would run adaptive workflow" in decision.message
