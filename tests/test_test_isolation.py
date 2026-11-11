from pathlib import Path
import os

from jarvis.memory.conversation import ConversationMemory
from jarvis.user_settings import JarvisSettings


def test_default_persistence_is_confined_to_test_workspace(tmp_path):
    assert Path.cwd() == tmp_path
    assert not os.getenv("OPENAI_API_KEY")
    memory = ConversationMemory()
    memory.add_turn("user", "Synthetic test message")
    JarvisSettings().save()
    assert memory.path.resolve().is_relative_to(tmp_path)
    assert (tmp_path / "data/settings.json").exists()
