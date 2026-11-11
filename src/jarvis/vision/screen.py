from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..models import CommandResult


@dataclass(frozen=True)
class ScreenCaptureResult:
    path: Path
    width: int
    height: int


class ScreenCapture:
    def __init__(self, *, output_dir: Path = Path("data/screenshots"), dry_run: bool = False) -> None:
        self.output_dir = output_dir
        self.dry_run = dry_run

    def capture(self) -> CommandResult:
        if self.dry_run:
            return CommandResult(
                True,
                "Would capture the current screen for vision analysis.",
                metadata={"screenshot_path": "", "privacy_sensitive": True},
            )

        try:
            from PIL import ImageGrab
        except ImportError:
            return CommandResult(
                False,
                "Pillow is not installed. Install screen vision with: pip install -e .[vision]",
                metadata={"pillow_available": False},
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"screen_{timestamp}.png"
        try:
            image = ImageGrab.grab(all_screens=True)
            image.save(path)
        except Exception as exc:
            return CommandResult(False, f"Screen capture failed: {exc}", metadata={"privacy_sensitive": True})

        return CommandResult(
            True,
            f"Captured screen: {path}",
            metadata={
                "screenshot_path": str(path),
                "width": int(image.width),
                "height": int(image.height),
                "privacy_sensitive": True,
            },
        )


class ScreenVision:
    def __init__(self, *, capture: ScreenCapture | None = None, ai=None, dry_run: bool = False) -> None:
        self.capture = capture or ScreenCapture(dry_run=dry_run)
        self.ai = ai
        self.dry_run = dry_run

    def describe(self, prompt: str = "What is on my screen?") -> CommandResult:
        cleaned = prompt.strip() or "What is on my screen?"
        capture_result = self.capture.capture()
        if not capture_result.ok:
            return capture_result

        screenshot_path = str(capture_result.metadata.get("screenshot_path", ""))
        if self.dry_run or not screenshot_path:
            return CommandResult(
                True,
                f"Would analyze the screen with vision: {cleaned}",
                metadata={
                    **capture_result.metadata,
                    "vision_prompt": cleaned,
                    "privacy_sensitive": True,
                },
            )

        if self.ai is None or not hasattr(self.ai, "describe_image"):
            return CommandResult(
                False,
                "AI vision is not configured yet.",
                metadata={**capture_result.metadata, "vision_prompt": cleaned, "privacy_sensitive": True},
            )

        result = self.ai.describe_image(screenshot_path, cleaned)
        return result.with_metadata(
            metadata={
                **capture_result.metadata,
                **result.metadata,
                "vision_prompt": cleaned,
                "privacy_sensitive": True,
            }
        )

    @staticmethod
    def status() -> CommandResult:
        try:
            import PIL.ImageGrab  # noqa: F401
        except ImportError:
            return CommandResult(
                False,
                "Pillow is not installed. Install screen vision with: pip install -e .[vision]",
                metadata={"pillow_available": False},
            )
        return CommandResult(True, "Pillow screen capture support is installed.", metadata={"pillow_available": True})
