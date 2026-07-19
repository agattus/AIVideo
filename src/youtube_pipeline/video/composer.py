"""MoviePy-based video composition: assets + audio + Ken Burns + captions."""

from __future__ import annotations

from pathlib import Path

from moviepy import (
    AudioFileClip,
    ColorClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)

from config.settings import Settings, get_settings
from youtube_pipeline.exceptions import VideoCompositionError
from youtube_pipeline.models import (
    AspectRatio,
    AudioArtifact,
    PipelineRequest,
    TimedScene,
    VisualStyle,
)
from youtube_pipeline.utils.files import ensure_dir
from youtube_pipeline.utils.logging import get_logger
from youtube_pipeline.video.captions import burn_captions
from youtube_pipeline.video.ken_burns import apply_ken_burns

logger = get_logger(__name__)


class VideoComposer:
    """Stitch timed scene assets into a final narrated video."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def compose(
        self,
        *,
        request: PipelineRequest,
        timed_scenes: list[TimedScene],
        audio: AudioArtifact,
        output_path: Path,
    ) -> Path:
        if not timed_scenes:
            raise VideoCompositionError("No timed scenes to compose")

        width, height = self._resolve_dimensions(request.aspect_ratio)
        fps = self.settings.video_fps
        ensure_dir(output_path.parent)

        visual_clips = []
        audio_clip = None
        final = None

        try:
            for timed in timed_scenes:
                clip = self._build_scene_clip(
                    timed,
                    width=width,
                    height=height,
                    enable_ken_burns=request.enable_ken_burns,
                    style=request.style,
                )
                visual_clips.append(clip)

            timeline = concatenate_videoclips(visual_clips, method="compose")
            audio_clip = AudioFileClip(str(audio.audio_path))
            # Keep visual timeline locked to audio duration.
            if timeline.duration and audio_clip.duration:
                if timeline.duration > audio_clip.duration:
                    timeline = timeline.subclipped(0, audio_clip.duration)
                elif timeline.duration < audio_clip.duration:
                    pad = ColorClip(
                        size=(width, height),
                        color=(0, 0, 0),
                        duration=audio_clip.duration - timeline.duration,
                    )
                    timeline = concatenate_videoclips([timeline, pad], method="compose")

            timeline = timeline.with_audio(audio_clip)

            if request.burn_captions and audio.subtitle_cues:
                timeline = burn_captions(
                    timeline,
                    audio.subtitle_cues,
                    visual_style=request.style,
                )

            final = timeline
            logger.info("Rendering video -> %s", output_path)
            final.write_videofile(
                str(output_path),
                fps=fps,
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

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise VideoCompositionError(f"Render produced empty file: {output_path}")

        logger.info(
            "Video rendered | path=%s | size=%d bytes",
            output_path,
            output_path.stat().st_size,
        )
        return output_path

    def _build_scene_clip(
        self,
        timed: TimedScene,
        *,
        width: int,
        height: int,
        enable_ken_burns: bool,
        style: VisualStyle,
    ):
        duration = timed.duration
        asset = timed.asset

        if asset is None:
            logger.warning(
                "Scene %d missing asset; using solid color placeholder",
                timed.scene.index,
            )
            return ColorClip(size=(width, height), color=(20, 20, 24), duration=duration)

        path = asset.path
        try:
            if asset.media_type == "video" or path.suffix.lower() in {
                ".mp4",
                ".mov",
                ".webm",
                ".mkv",
            }:
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
                return clip.resized(new_size=(width, height)).with_duration(duration)

            image = (
                ImageClip(str(path))
                .resized(new_size=(width, height))
                .with_duration(duration)
            )
            # Attach scene index so Ken Burns can alternate directions.
            setattr(image, "scene_index", timed.scene.index)
            if enable_ken_burns and style != VisualStyle.MINIMAL:
                image = apply_ken_burns(image)
            return image
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed building clip for scene %d: %s", timed.scene.index, exc)
            return ColorClip(size=(width, height), color=(20, 20, 24), duration=duration)

    def _resolve_dimensions(self, aspect_ratio: AspectRatio) -> tuple[int, int]:
        if aspect_ratio == AspectRatio.VERTICAL:
            return 1080, 1920
        if aspect_ratio == AspectRatio.SQUARE:
            return 1080, 1080
        return self.settings.video_width, self.settings.video_height

    @staticmethod
    def _close_clips(clips: list) -> None:
        for clip in clips:
            if clip is None:
                continue
            try:
                clip.close()
            except Exception:  # noqa: BLE001
                pass
