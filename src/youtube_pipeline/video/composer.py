"""MoviePy video composer: timed scenes, Ken Burns, Pillow captions, audio mux."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    VideoFileClip,
    concatenate_videoclips,
)

from config.settings import Settings, get_settings
from youtube_pipeline.exceptions import VideoCompositionError
from youtube_pipeline.models import PipelineResult, SceneData, VideoScript
from youtube_pipeline.utils.files import ensure_dir, slugify
from youtube_pipeline.utils.logging import get_logger
from youtube_pipeline.video.ken_burns import KenBurnsDirection, apply_ken_burns
from youtube_pipeline.video.text_clips import (
    create_caption_clip,
    phrase_timeline,
    resolve_font_path,
    split_script_into_phrases,
)

logger = get_logger(__name__)

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}

# Re-export for callers / tests that import from composer.
__all__ = ["VideoComposer", "create_caption_clip", "default_output_name"]


class VideoComposer:
    """Compose a final YouTube-ready MP4 from a timed ``VideoScript``.

    Captions are rendered with Pillow (``create_caption_clip``) — no ImageMagick
    installation is required. Scene narration is split into short, timed phrases
    so on-screen text changes dynamically across the scene duration.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        enable_ken_burns: bool = True,
        burn_captions: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self.width = width or self.settings.video_width
        self.height = height or self.settings.video_height
        self.fps = fps or self.settings.video_fps
        self.enable_ken_burns = enable_ken_burns
        self.burn_captions = burn_captions
        self._font = resolve_font_path()

    def compose(
        self,
        script: VideoScript,
        audio_path: str | Path,
        assets_dir: str | Path,
        output_path: str | Path,
    ) -> PipelineResult:
        """Render the final video and return a ``PipelineResult`` contract."""
        audio_file = Path(audio_path)
        assets_root = Path(assets_dir)
        destination = Path(output_path)

        self._validate_inputs(script, audio_file, assets_root)
        ensure_dir(destination.parent)

        asset_map = self._index_assets(assets_root)
        visual_clips: list[VideoClip] = []
        audio_clip: AudioFileClip | None = None
        final: VideoClip | None = None
        caption_phrase_count = 0

        try:
            for scene in script.scenes:
                duration = self._scene_duration(scene)
                asset_path = asset_map.get(scene.scene_id)
                clip = self._build_scene_clip(scene, asset_path, duration)
                if self.burn_captions:
                    clip, n_phrases = self._overlay_dynamic_captions(
                        clip, scene.script_text, duration
                    )
                    caption_phrase_count += n_phrases
                visual_clips.append(clip)

            if not visual_clips:
                raise VideoCompositionError("No visual clips were produced")

            logger.info(
                "Assembling timeline | scenes=%d | caption_phrases=%d",
                len(visual_clips),
                caption_phrase_count,
            )
            timeline = concatenate_videoclips(visual_clips, method="compose")
            audio_clip = AudioFileClip(str(audio_file))
            timeline = self._fit_timeline_to_audio(timeline, audio_clip)
            timeline = timeline.with_audio(audio_clip)
            final = timeline

            logger.info(
                "Encoding final video | size=%dx%d | fps=%d | out=%s",
                self.width,
                self.height,
                self.fps,
                destination,
            )
            final.write_videofile(
                str(destination),
                fps=self.fps,
                codec="libx264",
                audio_codec="aac",
                threads=4,
                preset="medium",
                logger=None,
            )
        except VideoCompositionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VideoCompositionError(f"Video composition failed: {exc}") from exc
        finally:
            self._close_clips([*visual_clips, audio_clip, final])

        if not destination.exists() or destination.stat().st_size == 0:
            raise VideoCompositionError(f"Render produced empty file: {destination}")

        result = PipelineResult(
            video_path=str(destination.resolve()),
            status="success",
            metadata={
                "title": script.title,
                "style": script.style,
                "scene_count": len(script.scenes),
                "total_duration": script.total_duration,
                "audio_path": str(audio_file.resolve()),
                "assets_dir": str(assets_root.resolve()),
                "width": self.width,
                "height": self.height,
                "fps": self.fps,
                "ken_burns": self.enable_ken_burns,
                "captions": self.burn_captions,
                "caption_phrases": caption_phrase_count,
                "caption_renderer": "pillow",
                "file_size_bytes": destination.stat().st_size,
            },
        )
        logger.info("Video rendered | path=%s", result.video_path)
        return result

    # ------------------------------------------------------------------
    # Validation / asset indexing
    # ------------------------------------------------------------------

    def _validate_inputs(
        self,
        script: VideoScript,
        audio_file: Path,
        assets_root: Path,
    ) -> None:
        if not script.scenes:
            raise VideoCompositionError("VideoScript.scenes must not be empty")
        if any(scene.duration <= 0 for scene in script.scenes):
            raise VideoCompositionError(
                "All SceneData.duration values must be > 0 before composition. "
                "Run AudioEngine.synthesize() (or populate_scene_durations) first."
            )
        if not audio_file.exists():
            raise VideoCompositionError(f"Audio track not found: {audio_file}")
        if audio_file.stat().st_size == 0:
            raise VideoCompositionError(f"Audio track is empty: {audio_file}")
        if not assets_root.exists() or not assets_root.is_dir():
            raise VideoCompositionError(f"Assets directory not found: {assets_root}")

    def _index_assets(self, assets_dir: Path) -> dict[int, Path]:
        """Map scene_id → media path (``scene_00.mp4``, ``scene_01.png``, …)."""
        pattern = re.compile(
            r"^(?:scene[_-]?)?(\d+)(?:[._-].+)?\.(?:jpg|jpeg|png|webp|bmp|tif|tiff|mp4|mov|webm|mkv|m4v|avi)$",
            re.IGNORECASE,
        )
        mapping: dict[int, Path] = {}
        for path in sorted(assets_dir.iterdir()):
            if not path.is_file():
                continue
            match = pattern.match(path.name)
            if not match:
                continue
            scene_id = int(match.group(1))
            if scene_id in mapping:
                continue
            mapping[scene_id] = path

        logger.info("Indexed %d visual assets from %s", len(mapping), assets_dir)
        return mapping

    # ------------------------------------------------------------------
    # Clip construction
    # ------------------------------------------------------------------

    def _scene_duration(self, scene: SceneData) -> float:
        return max(0.05, float(scene.duration))

    def _build_scene_clip(
        self,
        scene: SceneData,
        asset_path: Path | None,
        duration: float,
    ) -> VideoClip:
        if asset_path is None:
            logger.warning(
                "Scene %d missing asset; using solid placeholder",
                scene.scene_id,
            )
            return self._placeholder_clip(duration)

        suffix = asset_path.suffix.lower()
        try:
            if suffix in _VIDEO_EXTENSIONS:
                return self._build_video_clip(asset_path, duration)
            if suffix in _IMAGE_EXTENSIONS:
                return self._build_image_clip(asset_path, duration, scene.scene_id)
            logger.warning(
                "Unsupported asset type for scene %d (%s); using placeholder",
                scene.scene_id,
                suffix,
            )
            return self._placeholder_clip(duration)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed building clip for scene %d from %s: %s",
                scene.scene_id,
                asset_path,
                exc,
            )
            return self._placeholder_clip(duration)

    def _build_image_clip(self, path: Path, duration: float, scene_id: int) -> VideoClip:
        image = (
            ImageClip(str(path))
            .resized(new_size=(self.width, self.height))
            .with_duration(duration)
        )
        if not self.enable_ken_burns:
            return image

        direction = [
            KenBurnsDirection.ZOOM_IN,
            KenBurnsDirection.PAN_RIGHT,
            KenBurnsDirection.ZOOM_OUT,
            KenBurnsDirection.PAN_LEFT,
        ][scene_id % 4]
        setattr(image, "scene_index", scene_id)
        return apply_ken_burns(image, direction=direction, zoom_ratio=0.12)

    def _build_video_clip(self, path: Path, duration: float) -> VideoClip:
        clip = VideoFileClip(str(path))
        if clip.duration and clip.duration > duration:
            clip = clip.subclipped(0, duration)
        elif clip.duration and clip.duration < duration:
            pad = ColorClip(
                size=clip.size,
                color=(0, 0, 0),
                duration=duration - clip.duration,
            )
            clip = concatenate_videoclips([clip, pad], method="compose")
        return clip.resized(new_size=(self.width, self.height)).with_duration(duration)

    def _placeholder_clip(self, duration: float) -> VideoClip:
        return ColorClip(
            size=(self.width, self.height),
            color=(20, 20, 24),
            duration=duration,
        )

    # ------------------------------------------------------------------
    # Dynamic captions (Pillow, ImageMagick-free)
    # ------------------------------------------------------------------

    def _overlay_dynamic_captions(
        self,
        clip: VideoClip,
        text: str,
        duration: float,
    ) -> tuple[VideoClip, int]:
        """Overlay short, sequentially timed caption phrases over a scene clip."""
        phrases = split_script_into_phrases(text, scene_duration=duration)
        if not phrases:
            return clip, 0

        font_size = 54 if self.height >= 1080 else 42
        # Caption overlay uses full frame width; text is drawn near the bottom.
        overlay_size = (self.width, self.height)
        caption_clips: list[ImageClip] = []

        for phrase, start, end in phrase_timeline(phrases):
            phrase_duration = max(0.15, end - start)
            try:
                caption = create_caption_clip(
                    phrase,
                    phrase_duration,
                    size=overlay_size,
                    font_size=font_size,
                    font_path=self._font,
                )
                # Frame already paints text at the bottom; keep position at origin.
                caption = caption.with_start(start).with_position((0, 0))
                caption_clips.append(caption)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping caption phrase %r (%s)", phrase, exc)

        if not caption_clips:
            return clip, 0

        logger.debug(
            "Scene captions | phrases=%d | duration=%.2fs",
            len(caption_clips),
            duration,
        )
        composed = CompositeVideoClip(
            [clip, *caption_clips],
            size=(self.width, self.height),
        ).with_duration(duration)
        return composed, len(caption_clips)

    # ------------------------------------------------------------------
    # Timeline / audio fitting
    # ------------------------------------------------------------------

    def _fit_timeline_to_audio(
        self,
        timeline: VideoClip,
        audio_clip: AudioFileClip,
    ) -> VideoClip:
        visual_duration = float(timeline.duration or 0.0)
        audio_duration = float(audio_clip.duration or 0.0)
        if audio_duration <= 0:
            raise VideoCompositionError("Audio clip has invalid duration")

        if visual_duration > audio_duration + 0.05:
            logger.info(
                "Trimming visual timeline from %.2fs to audio %.2fs",
                visual_duration,
                audio_duration,
            )
            return timeline.subclipped(0, audio_duration)

        if visual_duration + 0.05 < audio_duration:
            pad_duration = audio_duration - visual_duration
            logger.info("Padding visual timeline by %.2fs to match audio", pad_duration)
            pad = ColorClip(
                size=(self.width, self.height),
                color=(0, 0, 0),
                duration=pad_duration,
            )
            return concatenate_videoclips([timeline, pad], method="compose")

        return timeline

    @staticmethod
    def _close_clips(clips: list[Any]) -> None:
        for clip in clips:
            if clip is None:
                continue
            try:
                clip.close()
            except Exception:  # noqa: BLE001
                pass


def default_output_name(script: VideoScript) -> str:
    """Helper used by the orchestrator for a stable MP4 basename."""
    return f"{slugify(script.title)}.mp4"
