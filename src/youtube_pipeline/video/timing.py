"""Map scenes onto the voiceover timeline."""

from __future__ import annotations

from youtube_pipeline.models import AudioArtifact, MediaAsset, Scene, ScriptPackage, TimedScene
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


def align_scenes_to_audio(
    script: ScriptPackage,
    audio: AudioArtifact,
    assets: list[MediaAsset],
) -> list[TimedScene]:
    """Allocate contiguous time ranges to each scene based on narration weight.

    Prefer duration hints when present; otherwise weight by narration length.
    Guarantees the final scene ends at audio.duration_seconds.
    """
    scenes = script.scenes
    if not scenes:
        return []

    assets_by_index = {a.scene_index: a for a in assets}
    weights = [_scene_weight(scene) for scene in scenes]
    total = float(sum(weights)) or float(len(scenes))
    duration = audio.duration_seconds

    timed: list[TimedScene] = []
    cursor = 0.0
    for idx, (scene, weight) in enumerate(zip(scenes, weights, strict=True)):
        if idx == len(scenes) - 1:
            end = duration
        else:
            end = min(duration, cursor + duration * (weight / total))
        if end <= cursor:
            end = min(duration, cursor + 0.5)
        timed.append(
            TimedScene(
                scene=scene,
                start=cursor,
                end=end,
                asset=assets_by_index.get(scene.index),
            )
        )
        cursor = end

    logger.info("Aligned %d scenes to %.2fs audio", len(timed), duration)
    return timed


def _scene_weight(scene: Scene) -> float:
    if scene.duration_hint_seconds and scene.duration_hint_seconds > 0:
        return float(scene.duration_hint_seconds)
    return float(max(1, len(scene.narration)))
