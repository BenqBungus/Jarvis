from __future__ import annotations

from jarvis.models import CommandResult
from jarvis.vision import ScreenVision


class FakeCapture:
    def capture(self) -> CommandResult:
        return CommandResult(
            True,
            "Captured fake screen.",
            metadata={
                "screenshot_path": "data/screenshots/fake.png",
                "width": 100,
                "height": 50,
                "privacy_sensitive": True,
            },
        )


class FakeAI:
    def describe_image(self, image_path: str, prompt: str) -> CommandResult:
        return CommandResult(True, f"vision: {prompt} @ {image_path}")


def test_screen_vision_describes_captured_image_with_ai():
    vision = ScreenVision(capture=FakeCapture(), ai=FakeAI())

    result = vision.describe("какво гледам")

    assert result.ok
    assert result.message == "vision: какво гледам @ data/screenshots/fake.png"
    assert result.metadata["privacy_sensitive"] is True
    assert result.metadata["vision_prompt"] == "какво гледам"


def test_screen_vision_dry_run_does_not_require_ai():
    vision = ScreenVision(dry_run=True)

    result = vision.describe("describe my screen")

    assert result.ok
    assert "Would analyze the screen" in result.message
    assert result.metadata["privacy_sensitive"] is True
