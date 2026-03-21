"""Directory-based demonstration library for demo-guided execution.

Stores demonstrations as sequences of (screenshot, action, metadata) on disk.
Retrieval uses perceptual hash (pHash) visual similarity alignment to find the
demo step whose screenshot is most similar to the agent's current screen state.
Falls back to sequential step index alignment when no screenshot is provided
or imagehash is not installed.  No embeddings or vector DBs -- just files on
disk and pHash comparison.

Supports optional VLM-based element description enrichment: instead of
returning raw coordinate instructions like ``CLICK(0.960, 0.066)``, enriched
demos produce human-readable guidance such as *"Click the three-dot menu in
the top-right corner of Chrome at approximately (0.960, 0.066)"*.  This is
the core value of the DemoLibrary -- rich, actionable guidance for agents.

Resolution normalization ensures that demos recorded at one resolution still
provide accurate coordinate guidance when the agent operates at a different
resolution.

Demonstration libraries for GUI agents follow the retrieval-augmented
approach in the agent literature, where pre-recorded expert trajectories
are stored, indexed, and retrieved at inference time to guide agent
behavior on similar tasks.

Usage:
    from openadapt_evals.demo_library import DemoLibrary

    library = DemoLibrary("./demos")
    demo_id = library.add_demo("notepad_1", screenshots=[...], actions=[...])

    # Enrich with VLM element descriptions (optional, requires API key)
    library.enrich_demo("notepad_1", demo_id=demo_id)

    guidance = library.align_step("notepad_1", current_screenshot, step_index=2)
    print(guidance.instruction)
    # -> "Click on three-dot menu button in Chrome toolbar at approximately (0.960, 0.066)"

Prior Art:
    - AgentTrek: Li et al., "AgentTrek: Agent Trajectory Synthesis via
      Guiding Replay with Web Tutorials", arXiv 2412.09605, 2024.
      Retrieval-augmented trajectory synthesis for web agents.
    - WebAgent: Gur et al., "A Real-World WebAgent with Planning, Long
      Context Understanding, and Program Synthesis", ICLR 2024.
      Demonstration-augmented web agent architecture.
    - RCI: Kim et al., "Language Models can Solve Computer Tasks",
      NeurIPS 2023. Recursive Criticism and Improvement with
      demonstration conditioning.
    - Retrieval-augmented generation: Lewis et al., "Retrieval-Augmented
      Generation for Knowledge-Intensive NLP Tasks", NeurIPS 2020.
      General RAG paradigm applied here to agent trajectories.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openadapt_evals.adapters.base import BenchmarkAction

try:
    import imagehash
    from PIL import Image

    _HAS_IMAGEHASH = True
except ImportError:
    _HAS_IMAGEHASH = False

logger = logging.getLogger(__name__)


@dataclass
class DemoStep:
    """A single step in a demonstration."""

    step_index: int
    screenshot_path: str  # relative to demo dir
    action_type: str
    action_description: str  # human-readable
    target_description: str  # what element was interacted with
    action_value: str  # text typed, key pressed, etc.
    metadata: dict[str, Any] = field(default_factory=dict)

    # Coordinates for click/drag actions (normalized 0-1)
    x: float | None = None
    y: float | None = None

    # VLM-generated element description (e.g., "three-dot menu button in
    # Chrome toolbar").  Populated by ``DemoLibrary.enrich_demo()`` or by
    # passing ``descriptions`` to ``add_demo()``.  Empty string if not
    # enriched.
    description: str = ""

    # Cached perceptual hash for visual similarity alignment.
    # Not serialized to demo.json -- computed lazily by
    # ``DemoLibrary._ensure_demo_phashes()``.
    _phash: Any = field(default=None, repr=False, compare=False)


@dataclass
class Demo:
    """A complete demonstration of a task."""

    task_id: str
    demo_id: str
    description: str  # what the demo accomplishes
    steps: list[DemoStep]
    created_at: str = ""  # ISO format
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class DemoGuidance:
    """Guidance from a demonstration for the current step.

    Returned by ``DemoLibrary.align_step()`` to tell the agent what the
    demo says to do at this point in the task.
    """

    available: bool  # whether demo guidance was found
    step_index: int  # which demo step this corresponds to
    instruction: str  # human-readable guidance text
    action_type: str  # expected action type
    action_value: str  # expected action value (text, key, etc.)
    target_description: str  # what to interact with
    screenshot_path: str | None  # path to demo screenshot for this step
    next_screenshot_path: str | None  # path to demo screenshot for next step
    confidence: float  # alignment confidence 0-1
    total_demo_steps: int  # total steps in the demo
    metadata: dict[str, Any] = field(default_factory=dict)

    # Visual alignment metadata -- populated when align_step() uses
    # perceptual hash matching instead of sequential index.
    visual_alignment_used: bool = False
    visual_distance: float | None = None  # pHash Hamming distance (lower=closer)

    def to_prompt_text(self) -> str:
        """Format guidance as text suitable for injection into an agent prompt.

        When VLM-enriched descriptions are available, the instruction line
        will include the element description (e.g., *"Click on three-dot
        menu button in Chrome toolbar at approximately (0.96, 0.07)"*)
        instead of raw coordinate notation.
        """
        if not self.available:
            return ""

        lines = [
            f"DEMONSTRATION GUIDANCE (step {self.step_index + 1}/{self.total_demo_steps}):",
            f"  Expected action: {self.action_type}",
        ]
        if self.target_description:
            lines.append(f"  Target: {self.target_description}")
        if self.action_value:
            lines.append(f"  Value: {self.action_value}")
        lines.append(f"  Instruction: {self.instruction}")
        lines.append(
            "  NOTE: Adapt if the current UI state differs from the demo. "
            "This is guidance, not a rigid script."
        )
        return "\n".join(lines)


def _demo_to_dict(demo: Demo) -> dict[str, Any]:
    """Serialize a Demo to a dict, stripping non-serializable internal fields.

    Removes ``DemoStep._phash`` which is a cached runtime value (an
    ``imagehash.ImageHash`` object) that should not be persisted.
    """
    data = asdict(demo)
    for step_dict in data.get("steps", []):
        step_dict.pop("_phash", None)
    return data


def _empty_guidance(step_index: int = 0) -> DemoGuidance:
    """Return empty guidance when no demo is available."""
    return DemoGuidance(
        available=False,
        step_index=step_index,
        instruction="",
        action_type="",
        action_value="",
        target_description="",
        screenshot_path=None,
        next_screenshot_path=None,
        confidence=0.0,
        total_demo_steps=0,
    )


class DemoLibrary:
    """Directory-based demonstration library.

    Directory structure::

        library_dir/
          {task_id}/
            {demo_id}/
              demo.json          # Demo metadata + steps
              step_000.png       # Screenshot for step 0
              step_001.png       # Screenshot for step 1
              ...

    Args:
        library_dir: Root directory for storing demos.
    """

    def __init__(self, library_dir: str = "demo_library"):
        self.library_dir = Path(library_dir)
        self.library_dir.mkdir(parents=True, exist_ok=True)

    def add_demo(
        self,
        task_id: str,
        screenshots: list[Path | bytes],
        actions: list[BenchmarkAction],
        description: str = "",
        metadata: dict[str, Any] | None = None,
        descriptions: list[str] | None = None,
        auto_enrich: bool = False,
        resolution: tuple[int, int] | None = None,
    ) -> str:
        """Record a new demonstration for a task.

        Args:
            task_id: Task identifier.
            screenshots: List of screenshot paths or raw PNG bytes,
                one per action.
            actions: List of ``BenchmarkAction`` objects from the demo.
            description: Human-readable description of the demo.
            metadata: Optional extra metadata.
            descriptions: Optional list of VLM element descriptions,
                one per step.  If provided, must match the length of
                *screenshots*/*actions*.  Each string describes the UI
                element interacted with (e.g., ``"three-dot menu button
                in Chrome toolbar"``).
            auto_enrich: If ``True`` and *descriptions* is not provided,
                automatically call ``enrich_demo()`` after saving.
                Requires a VLM API key (OPENAI_API_KEY).  Default
                ``False``.
            resolution: Optional ``(width, height)`` of the demo's
                original screen resolution.  Stored in demo metadata
                for coordinate normalization at retrieval time.  If
                ``None``, coordinates are used as-is.

        Returns:
            The generated demo_id.
        """
        if len(screenshots) != len(actions):
            raise ValueError(
                f"screenshots ({len(screenshots)}) and actions "
                f"({len(actions)}) must have the same length"
            )
        if descriptions is not None and len(descriptions) != len(actions):
            raise ValueError(
                f"descriptions ({len(descriptions)}) must match actions "
                f"({len(actions)}) length"
            )

        demo_id = uuid.uuid4().hex[:12]
        demo_dir = self.library_dir / task_id / demo_id
        demo_dir.mkdir(parents=True, exist_ok=True)

        steps: list[DemoStep] = []
        for i, (screenshot, action) in enumerate(zip(screenshots, actions)):
            # Save screenshot
            screenshot_filename = f"step_{i:03d}.png"
            screenshot_path = demo_dir / screenshot_filename

            if isinstance(screenshot, (str, Path)):
                # Copy file
                import shutil
                shutil.copy2(str(screenshot), str(screenshot_path))
            elif isinstance(screenshot, bytes):
                screenshot_path.write_bytes(screenshot)
            else:
                raise TypeError(
                    f"screenshot must be Path or bytes, got {type(screenshot)}"
                )

            # Build action description
            from openadapt_evals.agents.base import action_to_string
            action_desc = action_to_string(action)

            step_description = ""
            if descriptions is not None:
                step_description = descriptions[i]

            step = DemoStep(
                step_index=i,
                screenshot_path=screenshot_filename,
                action_type=action.type,
                action_description=action_desc,
                target_description=action.target_name or "",
                action_value=action.text or action.key or action.answer or "",
                x=action.x,
                y=action.y,
                metadata={},
                description=step_description,
            )
            steps.append(step)

        # Build demo metadata with resolution info
        demo_metadata = dict(metadata) if metadata else {}
        if resolution is not None:
            demo_metadata["resolution"] = {
                "width": resolution[0],
                "height": resolution[1],
            }

        demo = Demo(
            task_id=task_id,
            demo_id=demo_id,
            description=description or f"Demo for {task_id}",
            steps=steps,
            metadata=demo_metadata,
        )

        # Save demo.json
        demo_json_path = demo_dir / "demo.json"
        with open(demo_json_path, "w") as f:
            json.dump(_demo_to_dict(demo), f, indent=2)

        logger.info(
            "Saved demo %s for task %s (%d steps)",
            demo_id, task_id, len(steps),
        )

        # Auto-enrich with VLM descriptions if requested
        if auto_enrich and descriptions is None:
            try:
                self.enrich_demo(task_id, demo_id=demo_id)
            except Exception as exc:
                logger.warning(
                    "Auto-enrich failed for demo %s (continuing without "
                    "descriptions): %s",
                    demo_id, exc,
                )

        return demo_id

    def get_demo(self, task_id: str) -> Demo | None:
        """Get the most recent demo for a task.

        If multiple demos exist for a task, returns the most recently
        created one (by filesystem modification time).

        Args:
            task_id: Task identifier.

        Returns:
            Demo object or None if no demo exists.
        """
        task_dir = self.library_dir / task_id
        if not task_dir.is_dir():
            return None

        # Find all demo directories, sorted by modification time (newest first)
        demo_dirs = sorted(
            [d for d in task_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )

        for demo_dir in demo_dirs:
            demo_json = demo_dir / "demo.json"
            if not demo_json.exists():
                continue
            try:
                with open(demo_json) as f:
                    data = json.load(f)
                steps = [DemoStep(**s) for s in data.pop("steps", [])]
                return Demo(steps=steps, **data)
            except (json.JSONDecodeError, TypeError, KeyError) as exc:
                logger.warning(
                    "Skipping invalid demo %s: %s", demo_dir.name, exc,
                )

        return None

    def list_demos(self, task_id: str) -> list[str]:
        """List all demo IDs for a task.

        Args:
            task_id: Task identifier.

        Returns:
            List of demo_id strings.
        """
        task_dir = self.library_dir / task_id
        if not task_dir.is_dir():
            return []
        return [
            d.name
            for d in task_dir.iterdir()
            if d.is_dir() and (d / "demo.json").exists()
        ]

    def list_tasks(self) -> list[str]:
        """List all task IDs that have at least one demo.

        Returns:
            List of task_id strings.
        """
        if not self.library_dir.is_dir():
            return []
        return [
            d.name
            for d in self.library_dir.iterdir()
            if d.is_dir() and any(
                (sub / "demo.json").exists()
                for sub in d.iterdir()
                if sub.is_dir()
            )
        ]

    def align_step(
        self,
        task_id: str,
        current_screenshot: bytes | None,
        step_index: int,
        current_resolution: tuple[int, int] | None = None,
        use_visual_alignment: bool = True,
    ) -> DemoGuidance:
        """Get demo guidance for a specific step.

        When *use_visual_alignment* is ``True`` and *current_screenshot*
        is provided, alignment uses perceptual hash (pHash) similarity
        to find the demo step whose screenshot is most similar to the
        current screen state.  This is critical when the agent takes a
        different number of steps than the demo -- sequential step index
        alignment breaks, but the visual state still matches.

        Falls back to sequential ``step_index`` alignment when visual
        alignment is disabled, no screenshot is provided, or
        ``imagehash`` is not installed.

        When VLM-enriched descriptions are available, the returned
        instruction uses the description instead of raw coordinate
        notation.  For example, instead of ``CLICK(0.960, 0.066)`` the
        instruction becomes *"Click on three-dot menu button in Chrome
        toolbar at approximately (0.960, 0.066)"*.

        If *current_resolution* is provided and the demo has stored
        resolution metadata, coordinates are proportionally normalized
        so that guidance remains accurate across different screen sizes.

        Args:
            task_id: Task identifier.
            current_screenshot: Current screenshot bytes.  When provided
                with *use_visual_alignment=True*, enables pHash-based
                demo step matching instead of sequential index.
            step_index: Current step index in the agent's execution.
                Used as fallback when visual alignment is disabled or
                unavailable.
            current_resolution: Optional ``(width, height)`` of the
                agent's current screen.  When provided and the demo has
                stored resolution metadata, coordinates are
                proportionally normalized.
            use_visual_alignment: Whether to use perceptual hash
                similarity for step alignment.  Defaults to ``True``.
                Set to ``False`` to force sequential index alignment
                (original behavior).

        Returns:
            DemoGuidance with the demo's recommendation for this step.
        """
        demo = self.get_demo(task_id)
        if demo is None:
            return _empty_guidance(step_index)

        total_steps = len(demo.steps)
        if total_steps == 0:
            return _empty_guidance(step_index)

        # --- Visual similarity alignment ------------------------------------
        visual_alignment_used = False
        visual_distance: float | None = None
        demo_dir = self._demo_dir(task_id, demo.demo_id)

        if (
            use_visual_alignment
            and current_screenshot is not None
            and _HAS_IMAGEHASH
        ):
            matched_idx, distance = self._find_closest_demo_step(
                current_screenshot, demo, demo_dir,
            )
            step = demo.steps[matched_idx]
            visual_alignment_used = True
            visual_distance = float(distance)
            # Confidence: distance 0 -> 1.0, distance 32 -> 0.5,
            # distance 64 -> 0.0.  pHash is 64-bit so max distance=64.
            confidence = max(0.0, 1.0 - distance / 64.0)
            logger.info(
                "Visual alignment: step_index=%d matched demo step %d "
                "(distance=%d, confidence=%.2f) for task %s",
                step_index, matched_idx, distance, confidence, task_id,
            )
        elif step_index < total_steps:
            # Sequential alignment: use step_index directly
            step = demo.steps[step_index]
            confidence = 1.0
        else:
            # Past the end of the demo -- return the last step as context
            # with low confidence
            step = demo.steps[-1]
            confidence = 0.2
            logger.info(
                "Step %d exceeds demo length %d for task %s, "
                "returning last step with low confidence",
                step_index, total_steps, task_id,
            )

        # Resolve screenshot paths
        screenshot_path = str(demo_dir / step.screenshot_path) if step.screenshot_path else None

        next_screenshot_path = None
        if step.step_index + 1 < total_steps:
            next_step = demo.steps[step.step_index + 1]
            next_screenshot_path = str(demo_dir / next_step.screenshot_path) if next_step.screenshot_path else None

        # --- Resolution normalization ----------------------------------------
        norm_x = step.x
        norm_y = step.y
        if (
            current_resolution is not None
            and norm_x is not None
            and norm_y is not None
        ):
            demo_res = demo.metadata.get("resolution")
            if demo_res:
                demo_w = demo_res.get("width")
                demo_h = demo_res.get("height")
                cur_w, cur_h = current_resolution
                if demo_w and demo_h and demo_w > 0 and demo_h > 0:
                    norm_x = step.x * cur_w / demo_w
                    norm_y = step.y * cur_h / demo_h

        # --- Build instruction with VLM description -------------------------
        instruction = _build_enriched_instruction(
            step=step,
            normalized_x=norm_x,
            normalized_y=norm_y,
        )

        return DemoGuidance(
            available=True,
            step_index=step.step_index,
            instruction=instruction,
            action_type=step.action_type,
            action_value=step.action_value,
            target_description=step.target_description,
            screenshot_path=screenshot_path,
            next_screenshot_path=next_screenshot_path,
            confidence=confidence,
            total_demo_steps=total_steps,
            visual_alignment_used=visual_alignment_used,
            visual_distance=visual_distance,
        )

    def enrich_demo(
        self,
        task_id: str,
        demo_id: str | None = None,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        crop_radius: int = 80,
    ) -> None:
        """Generate VLM element descriptions for each click step in a demo.

        For each step with a ``click`` action and a screenshot, crops a
        region around the click coordinates and sends the full screenshot
        plus the cropped region to a VLM.  The VLM responds with a short
        description of the UI element at that location (e.g., *"three-dot
        menu button in Chrome toolbar"*).

        Descriptions are stored in each ``DemoStep.description`` field
        and persisted to ``demo.json``.

        This method is idempotent -- steps that already have a non-empty
        ``description`` are skipped.

        Args:
            task_id: Task identifier.
            demo_id: Specific demo to enrich.  If ``None``, enriches the
                most recent demo for the task.
            model: VLM model name for element description calls.
            provider: VLM provider (``"openai"`` or ``"anthropic"``).
            crop_radius: Pixel radius around the click point to crop
                for the detail image sent to the VLM.

        Raises:
            ValueError: If no demo is found for the task.
        """
        if demo_id is not None:
            demo_dir = self._demo_dir(task_id, demo_id)
            demo_json = demo_dir / "demo.json"
            if not demo_json.exists():
                raise ValueError(
                    f"No demo.json found at {demo_dir}"
                )
            with open(demo_json) as f:
                data = json.load(f)
            steps = [DemoStep(**s) for s in data.pop("steps", [])]
            demo = Demo(steps=steps, **data)
        else:
            demo = self.get_demo(task_id)
            if demo is None:
                raise ValueError(f"No demo found for task {task_id}")
            demo_dir = self._demo_dir(task_id, demo.demo_id)

        enriched_count = 0
        for step in demo.steps:
            # Skip non-click steps and steps already enriched
            if step.action_type != "click":
                continue
            if step.description:
                continue
            if step.x is None or step.y is None:
                continue
            if not step.screenshot_path:
                continue

            screenshot_file = demo_dir / step.screenshot_path
            if not screenshot_file.exists():
                logger.warning(
                    "Screenshot %s not found, skipping enrichment for "
                    "step %d",
                    screenshot_file, step.step_index,
                )
                continue

            try:
                desc = _vlm_describe_element(
                    screenshot_path=screenshot_file,
                    click_x=step.x,
                    click_y=step.y,
                    model=model,
                    provider=provider,
                    crop_radius=crop_radius,
                )
                if desc:
                    step.description = desc
                    enriched_count += 1
                    logger.info(
                        "Step %d enriched: %s", step.step_index, desc,
                    )
            except Exception as exc:
                logger.warning(
                    "VLM enrichment failed for step %d: %s",
                    step.step_index, exc,
                )

        if enriched_count > 0:
            # Persist updated demo
            demo_json_path = demo_dir / "demo.json"
            with open(demo_json_path, "w") as f:
                json.dump(_demo_to_dict(demo), f, indent=2)
            logger.info(
                "Enriched %d steps in demo %s for task %s",
                enriched_count, demo.demo_id, task_id,
            )
        else:
            logger.info(
                "No steps needed enrichment in demo %s for task %s",
                demo.demo_id, task_id,
            )

    def _find_closest_demo_step(
        self,
        current_screenshot: bytes,
        demo: Demo,
        demo_dir: Path,
    ) -> tuple[int, int]:
        """Find the demo step whose screenshot is most similar to current state.

        Uses perceptual hashing (pHash) to compare the current screenshot
        against all demo screenshots.  Returns the index of the closest
        match and the Hamming distance.

        Demo screenshot hashes are cached on the ``DemoStep._phash``
        field so they are only computed once per session.

        Args:
            current_screenshot: PNG bytes of the current screen.
            demo: The demo to search.
            demo_dir: Directory containing the demo's screenshot files.

        Returns:
            Tuple of ``(best_step_index, hamming_distance)``.
        """
        current_img = Image.open(io.BytesIO(current_screenshot))
        current_hash = imagehash.phash(current_img)

        # Ensure all demo step pHashes are computed
        self._ensure_demo_phashes(demo, demo_dir)

        best_step = 0
        best_distance = float("inf")
        for i, step in enumerate(demo.steps):
            if step._phash is None:
                continue
            distance = current_hash - step._phash
            if distance < best_distance:
                best_distance = distance
                best_step = i

        # If no step had a valid hash, return step 0 with max distance
        if best_distance == float("inf"):
            return 0, 64

        return best_step, int(best_distance)

    def _ensure_demo_phashes(self, demo: Demo, demo_dir: Path) -> None:
        """Compute and cache pHash for each demo step's screenshot.

        Only computes hashes for steps that don't already have one
        cached in ``step._phash``.  This means the first call per demo
        does the work and all subsequent calls are free.

        Args:
            demo: Demo whose steps need hashes.
            demo_dir: Directory containing the demo's screenshot files.
        """
        for step in demo.steps:
            if step._phash is not None:
                continue
            if not step.screenshot_path:
                continue
            screenshot_file = demo_dir / step.screenshot_path
            if not screenshot_file.exists():
                logger.debug(
                    "Screenshot %s not found, skipping pHash for step %d",
                    screenshot_file, step.step_index,
                )
                continue
            try:
                img = Image.open(screenshot_file)
                step._phash = imagehash.phash(img)
            except Exception as exc:
                logger.warning(
                    "Failed to compute pHash for step %d: %s",
                    step.step_index, exc,
                )

    def _demo_dir(self, task_id: str, demo_id: str) -> Path:
        """Get the directory for a specific demo."""
        return self.library_dir / task_id / demo_id


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

# VLM prompt for element description enrichment.
_ENRICH_PROMPT = (
    "What UI element is at the highlighted location in the screenshot? "
    "Describe it in 5-10 words (e.g., 'three-dot menu button in Chrome "
    "toolbar'). Reply with ONLY the description, no extra text."
)


def _build_enriched_instruction(
    step: DemoStep,
    normalized_x: float | None = None,
    normalized_y: float | None = None,
) -> str:
    """Build a human-readable instruction from a DemoStep.

    When the step has a VLM-generated ``description``, the instruction
    reads like *"Click on three-dot menu button in Chrome toolbar at
    approximately (0.960, 0.066)"* instead of the raw
    ``CLICK(0.960, 0.066)`` notation.

    For non-click actions or steps without descriptions, falls back to
    the original ``action_description``.

    Args:
        step: The demo step to build an instruction for.
        normalized_x: X coordinate (potentially resolution-normalized).
        normalized_y: Y coordinate (potentially resolution-normalized).

    Returns:
        Human-readable instruction string.
    """
    if step.description and step.action_type == "click":
        # Rich instruction with element description
        if normalized_x is not None and normalized_y is not None:
            return (
                f"Click on {step.description} at approximately "
                f"({normalized_x:.3f}, {normalized_y:.3f})"
            )
        return f"Click on {step.description}"

    # Fallback: original action description
    return step.action_description


def _vlm_describe_element(
    screenshot_path: Path,
    click_x: float,
    click_y: float,
    model: str = "gpt-4o-mini",
    provider: str = "openai",
    crop_radius: int = 80,
) -> str:
    """Use a VLM to describe the UI element at a click location.

    Sends the full screenshot and a cropped region around the click
    point to the VLM, which returns a short element description.

    Args:
        screenshot_path: Path to the full screenshot PNG.
        click_x: Click X coordinate (normalized 0-1).
        click_y: Click Y coordinate (normalized 0-1).
        model: VLM model name.
        provider: VLM provider.
        crop_radius: Pixel radius for the crop around the click point.

    Returns:
        Element description string, or empty string on failure.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning(
            "Pillow is not installed -- cannot crop screenshots for "
            "VLM enrichment.  Install with: pip install Pillow"
        )
        return ""

    # Load and crop the screenshot
    img = Image.open(screenshot_path)
    img_w, img_h = img.size

    # Convert normalized coordinates to pixel coordinates
    px = int(click_x * img_w)
    py = int(click_y * img_h)

    # Crop a region around the click point (clamped to image bounds)
    x1 = max(0, px - crop_radius)
    y1 = max(0, py - crop_radius)
    x2 = min(img_w, px + crop_radius)
    y2 = min(img_h, py + crop_radius)
    crop = img.crop((x1, y1, x2, y2))

    # Draw a crosshair on the crop to highlight the exact click point
    from PIL import ImageDraw

    draw = ImageDraw.Draw(crop)
    cx = px - x1  # click point relative to crop
    cy = py - y1
    line_color = (255, 0, 0)  # red
    draw.line([(cx - 10, cy), (cx + 10, cy)], fill=line_color, width=2)
    draw.line([(cx, cy - 10), (cx, cy + 10)], fill=line_color, width=2)

    # Convert both images to bytes
    import io

    full_buf = io.BytesIO()
    img.save(full_buf, format="PNG")
    full_bytes = full_buf.getvalue()

    crop_buf = io.BytesIO()
    crop.save(crop_buf, format="PNG")
    crop_bytes = crop_buf.getvalue()

    # VLM call
    from openadapt_evals.vlm import vlm_call

    raw = vlm_call(
        _ENRICH_PROMPT,
        images=[full_bytes, crop_bytes],
        model=model,
        provider=provider,
        max_tokens=64,
        temperature=0.0,
    )

    # Clean up the response (strip quotes, whitespace, periods)
    desc = raw.strip().strip('"').strip("'").strip(".").strip()
    return desc
