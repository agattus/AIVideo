"""FFmpeg-based cinematic assembler with Ken Burns zoompan."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from config.settings import Settings, get_settings
from youtube_pipeline.exceptions import VideoCompositionError
from youtube_pipeline.models import PipelineResult, VideoScript
from youtube_pipeline.utils.files import ensure_dir, slugify
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["FFmpegComposer", "default_output_name"]


def default_output_name(script: VideoScript) -> str:
    return f"{slugify(script.title)}.mp4"


def _resolve_ffmpeg() -> str:
    which = shutil.which("ffmpeg")
    if which:
        return which
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise VideoCompositionError(f"ffmpeg binary not found: {exc}") from exc


class FFmpegComposer:
    """Assemble scene stills into an MP4 using FFmpeg ``zoompan`` Ken Burns."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        enable_ken_burns: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self.width = width or self.settings.video_width
        self.height = height or self.settings.video_height
        self.fps = fps or self.settings.video_fps
        self.enable_ken_burns = enable_ken_burns
        self._ffmpeg = _resolve_ffmpeg()

    def compose(
        self,
        script: VideoScript,
        audio_path: str | Path,
        assets_dir: str | Path,
        output_path: str | Path,
    ) -> PipelineResult:
        audio_file = Path(audio_path)
        assets_root = Path(assets_dir)
        destination = Path(output_path)
        ensure_dir(destination.parent)

        if not script.scenes:
            raise VideoCompositionError("VideoScript.scenes is empty")
        if not audio_file.exists():
            raise VideoCompositionError(f"Audio not found: {audio_file}")

        work = ensure_dir(destination.parent / "_ffmpeg_work")
        clip_paths: list[Path] = []
        try:
            for index, scene in enumerate(script.scenes):
                image = self._resolve_scene_image(assets_root, scene.scene_id)
                duration = max(0.2, float(scene.duration or 2.0))
                clip = work / f"clip_{scene.scene_id:02d}.mp4"
                self._render_scene_clip(image, clip, duration=duration, scene_index=index)
                clip_paths.append(clip)

            silent_video = work / "video_silent.mp4"
            self._concat_clips(clip_paths, silent_video)

            bgm = assets_root / "bgm.mp3"
            self._mux_audio(
                silent_video,
                audio_file,
                destination,
                bgm_path=bgm if bgm.exists() and bgm.stat().st_size > 1024 else None,
            )

            if not destination.exists() or destination.stat().st_size == 0:
                raise VideoCompositionError(f"FFmpeg produced empty file: {destination}")

            return PipelineResult(
                video_path=str(destination.resolve()),
                status="success",
                metadata={
                    "title": script.title,
                    "style": script.style,
                    "scene_count": len(script.scenes),
                    "width": self.width,
                    "height": self.height,
                    "fps": self.fps,
                    "ken_burns": self.enable_ken_burns,
                    "composer": "ffmpeg_zoompan",
                    "file_size_bytes": destination.stat().st_size,
                    "bgm": bool(bgm.exists() and bgm.stat().st_size > 1024),
                },
            )
        except VideoCompositionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VideoCompositionError(f"FFmpeg composition failed: {exc}") from exc
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _resolve_scene_image(self, assets_dir: Path, scene_id: int) -> Path:
        for name in (
            f"scene_{scene_id:02d}.jpg",
            f"scene_{scene_id:02d}.jpeg",
            f"scene_{scene_id:02d}.png",
            f"scene_{scene_id}.jpg",
        ):
            path = assets_dir / name
            if path.exists() and path.stat().st_size > 256:
                return path
        raise VideoCompositionError(f"Missing image for scene {scene_id}: scene_{scene_id:02d}.jpg")

    def _render_scene_clip(
        self,
        image: Path,
        dest: Path,
        *,
        duration: float,
        scene_index: int,
    ) -> None:
        frames = max(1, int(round(duration * self.fps)))
        # Alternate gentle zoom-in / zoom-out for cinematic variety.
        if self.enable_ken_burns:
            if scene_index % 2 == 0:
                # Zoom in: 1.0 → 1.12
                zoom = "min(zoom+0.0015,1.12)"
            else:
                # Zoom out: start higher and ease down
                zoom = "if(eq(on,1),1.12,max(zoom-0.0015,1.0))"
            vf = (
                f"scale={self.width * 2}:{self.height * 2},"
                f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={frames}:s={self.width}x{self.height}:fps={self.fps},"
                f"format=yuv420p"
            )
        else:
            vf = f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,crop={self.width}:{self.height},fps={self.fps},format=yuv420p"

        cmd = [
            self._ffmpeg,
            "-y",
            "-loop",
            "1",
            "-i",
            str(image),
            "-vf",
            vf,
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(dest),
        ]
        self._run(cmd, label=f"scene-clip:{image.name}")

    def _concat_clips(self, clips: list[Path], dest: Path) -> None:
        list_file = dest.with_suffix(".txt")
        list_file.write_text(
            "".join(f"file '{c.resolve()}'\n" for c in clips),
            encoding="utf-8",
        )
        cmd = [
            self._ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(dest),
        ]
        self._run(cmd, label="concat")

    def _mux_audio(
        self,
        video: Path,
        voiceover: Path,
        dest: Path,
        *,
        bgm_path: Path | None,
    ) -> None:
        if bgm_path is None:
            cmd = [
                self._ffmpeg,
                "-y",
                "-i",
                str(video),
                "-i",
                str(voiceover),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(dest),
            ]
            self._run(cmd, label="mux-voiceover")
            return

        # Duck BGM under narration (~10% volume) with short fades.
        filter_complex = (
            "[1:a]volume=1.05[vo];"
            "[2:a]volume=0.10,afade=t=in:st=0:d=1.5,afade=t=out:st=0:d=1.5[bg];"
            "[vo][bg]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
        # afade out needs duration — approximate via apad+atrim after amix instead.
        filter_complex = (
            "[1:a]volume=1.05[vo];"
            "[2:a]aloop=loop=-1:size=2e+09,volume=0.10[bg];"
            "[vo][bg]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
        cmd = [
            self._ffmpeg,
            "-y",
            "-i",
            str(video),
            "-i",
            str(voiceover),
            "-i",
            str(bgm_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(dest),
        ]
        self._run(cmd, label="mux-voiceover-bgm")

    def _run(self, cmd: list[str], *, label: str) -> None:
        logger.info("FFmpeg %s | %s", label, " ".join(cmd[:8]) + " …")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-1200:]
            raise VideoCompositionError(f"ffmpeg {label} failed ({proc.returncode}): {tail}")
