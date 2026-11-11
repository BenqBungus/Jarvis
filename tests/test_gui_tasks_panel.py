from jarvis.gui.tasks_panel import TasksPanel


def test_tasks_panel_submits_goal_and_shows_progress(qapp):
    panel = TasksPanel()
    submitted = []
    panel.command_requested.connect(lambda text, source: submitted.append((text, source)))
    panel.goal.setText("compare products")
    panel.run_button.click()
    assert submitted == [("agent mode compare products", "task")]
    panel.set_task_state(True, "Planning")
    assert panel.stop_button.isEnabled()
    assert not panel.run_button.isEnabled()
    panel.add_progress("Step 1: Read source")
    assert panel.events.item(0).text() == "Step 1: Read source"
    panel.set_task_state(False, "Completed")
    assert panel.run_button.isEnabled()
    panel.close()
