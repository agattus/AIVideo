"""FFmpeg-based cinematic assembler with Ken Burns zoompan + burned-in captions."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from config.settings import Settings, get_settings
from youtube_pipeline.exceptions import VideoCompositionError
from youtube_pipeline.models import PipelineResult, VideoScript
from youtube_pipeline.utils.files import ensure_dir, slugify
from youtube_pipeline.utils.logging import get_logger
from youtube_pipeline.video.text_clips import (
    render_caption_rgba,
    scene_caption_timeline,
)

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


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


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
        burn_captions: bool = True,
        aspect_ratio: str = "16:9",
    ) -> None:
        self.settings = settings or get_settings()
        self.width = width or self.settings.video_width
        self.height = height or self.settings.video_height
        self.fps = fps or self.settings.video_fps
        self.enable_ken_burns = enable_ken_burns
        self.burn_captions = burn_captions
        self.aspect_ratio = aspect_ratio
        self._ffmpeg = _resolve_ffmpeg()

    def compose(
        self,
        script: VideoScript,
        audio_path: str | Path,
        assets_dir: str | Path,
        output_path: str | Path,
        *,
        timing: dict[str, Any] | None = None,
        language: str = "en",
    ) -> PipelineResult:
        audio_file = Path(audio_path)
        assets_root = Path(assets_dir)
        destination = Path(output_path)
        ensure_dir(destination.parent)

        if not script.scenes:
            raise VideoCompositionError("VideoScript.scenes is empty")
        if not audio_file.exists():
            raise VideoCompositionError(f"Audio not found: {audio_file}")

        audio_duration = self._probe_duration(audio_file)
        scene_durations = self._aligned_scene_durations(script, audio_duration)
        frame_counts = self._allocate_scene_frames(scene_durations)
        timing_words = list((timing or {}).get("words") or [])
        timing_scenes = list((timing or {}).get("scenes") or [])

        work = ensure_dir(destination.parent / "_ffmpeg_work")
        clip_paths: list[Path] = []
        srt_cues: list[tuple[int, float, float, str]] = []
        timeline_cursor = 0.0
        caption_phrase_count = 0

        try:
            for index, scene in enumerate(script.scenes):
                image = self._resolve_scene_image(assets_root, scene.scene_id)
                duration = scene_durations[index]
                frames = frame_counts[index]
                # Exact clip length from integer frames — keeps voice/video locked.
                clip_duration = frames / float(self.fps)

                scene_abs_start = timeline_cursor
                if index < len(timing_scenes) and isinstance(timing_scenes[index], dict):
                    try:
                        scene_abs_start = float(
                            timing_scenes[index].get("start", timeline_cursor)
                        )
                    except (TypeError, ValueError):
                        scene_abs_start = timeline_cursor

                caption_cues: list[tuple[str, float, float]] = []
                quiz_overlay: str | None = None
                phase = (getattr(scene, "phase", None) or "").strip().lower()
                if phase == "question":
                    quiz_overlay = (scene.question or scene.script_text or "").strip()
                elif phase == "answer":
                    quiz_overlay = (scene.answer or scene.script_text or "").strip()

                if self.burn_captions and quiz_overlay:
                    # Full-scene on-screen card for quiz question / answer reveal.
                    caption_cues = [(quiz_overlay, 0.0, clip_duration)]
                elif self.burn_captions:
                    caption_cues = scene_caption_timeline(
                        scene.script_text or "",
                        scene_duration=clip_duration,
                        words=timing_words or None,
                        scene_start=scene_abs_start,
                    )

                clip = work / f"clip_{scene.scene_id:02d}.mp4"
                self._render_scene_clip(
                    image,
                    clip,
                    duration=clip_duration,
                    frames=frames,
                    scene_index=index,
                    caption_cues=caption_cues,
                    work_dir=work / f"caps_{scene.scene_id:02d}",
                    language=language,
                    quiz_card=bool(quiz_overlay),
                    quiz_phase=phase or None,
                )
                clip_paths.append(clip)

                for text, start, end in caption_cues:
                    srt_cues.append(
                        (
                            len(srt_cues) + 1,
                            timeline_cursor + start,
                            timeline_cursor + end,
                            text,
                        )
                    )
                    caption_phrase_count += 1
                timeline_cursor += clip_duration

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

            srt_path = destination.with_suffix(".srt")
            if srt_cues:
                self._write_srt(srt_path, srt_cues)
            else:
                srt_path = None

            return PipelineResult(
                video_path=str(destination.resolve()),
                status="success",
                metadata={
                    "title": script.title,
                    "style": script.style,
                    "scene_count": len(script.scenes),
                    "width": self.width,
                    "height": self.height,
                    "aspect_ratio": self.aspect_ratio,
                    "fps": self.fps,
                    "ken_burns": self.enable_ken_burns,
                    "burn_captions": self.burn_captions,
                    "caption_phrases": caption_phrase_count,
                    "caption_sync": "word_timestamps" if timing_words else "proportional",
                    "audio_duration": audio_duration,
                    "video_duration": timeline_cursor,
                    "srt_path": str(srt_path.resolve()) if srt_path else None,
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

    @staticmethod
    def _probe_duration(path: Path) -> float:
        try:
            from config.settings import Settings, TTSProvider
            from youtube_pipeline.audio.tts import AudioEngine

            engine = AudioEngine(Settings(tts_provider=TTSProvider.EDGE_TTS))
            return float(engine._probe_duration_seconds(path))
        except Exception:  # noqa: BLE001
            return 0.0

    def _aligned_scene_durations(
        self, script: VideoScript, audio_duration: float
    ) -> list[float]:
        """Scale scene durations so the visual timeline matches the voiceover."""
        raw = [max(0.2, float(scene.duration or 2.0)) for scene in script.scenes]
        total = sum(raw)
        if total <= 0:
            n = max(1, len(raw))
            fill = max(0.2, (audio_duration or n * 2.0) / n)
            return [fill] * n
        if audio_duration > 0.5 and abs(total - audio_duration) > 0.08:
            scale = audio_duration / total
            scaled = [max(0.2, d * scale) for d in raw]
            scaled[-1] = max(0.2, scaled[-1] + (audio_duration - sum(scaled)))
            logger.info(
                "Aligned scene durations to audio | script=%.2fs audio=%.2fs",
                total,
                audio_duration,
            )
            return scaled
        return raw

    def _allocate_scene_frames(self, durations: list[float]) -> list[int]:
        """Integer frame counts that sum to round(sum(durations)*fps)."""
        if not durations:
            return []
        total_dur = sum(durations)
        total_frames = max(len(durations), int(round(total_dur * self.fps)))
        raw = [(d / total_dur) * total_frames for d in durations]
        frames = [max(1, int(r)) for r in raw]
        # Largest-remainder so the sum matches exactly.
        while sum(frames) < total_frames:
            frac = [r - f for r, f in zip(raw, frames, strict=True)]
            frames[frac.index(max(frac))] += 1
        while sum(frames) > total_frames:
            # Prefer trimming the longest clip.
            idx = max(range(len(frames)), key=lambda i: frames[i])
            if frames[idx] <= 1:
                break
            frames[idx] -= 1
        return frames

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

    def _caption_font_size(self) -> int:
        if self.height > self.width:
            return 64
        if self.width == self.height:
            return 56
        return 52

    def _render_scene_clip(
        self,
        image: Path,
        dest: Path,
        *,
        duration: float,
        frames: int,
        scene_index: int,
        caption_cues: list[tuple[str, float, float]],
        work_dir: Path,
        language: str = "en",
        quiz_card: bool = False,
        quiz_phase: str | None = None,
    ) -> None:
        frames = max(1, int(frames))
        # Alternate gentle zoom-in / zoom-out for cinematic variety.
        if self.enable_ken_burns:
            if scene_index % 2 == 0:
                zoom = "min(zoom+0.0015,1.12)"
            else:
                zoom = "if(eq(on,1),1.12,max(zoom-0.0015,1.0))"
            vf = (
                f"scale={self.width * 2}:{self.height * 2},"
                f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={frames}:s={self.width}x{self.height}:fps={self.fps},"
                f"format=yuv420p"
            )
        else:
            vf = (
                f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
                f"crop={self.width}:{self.height},fps={self.fps},format=yuv420p"
            )

        base_clip = dest.with_name(dest.stem + "_base.mp4")
        cmd = [
            self._ffmpeg,
            "-y",
            "-loop",
            "1",
            "-i",
            str(image),
            "-vf",
            vf,
            "-frames:v",
            str(frames),
            "-t",
            f"{duration:.6f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(base_clip),
        ]
        self._run(cmd, label=f"scene-clip:{image.name}")

        if not caption_cues:
            shutil.move(str(base_clip), str(dest))
            return

        self._overlay_caption_phrases(
            base_clip,
            dest,
            caption_cues=caption_cues,
            work_dir=work_dir,
            language=language,
            quiz_card=quiz_card,
            quiz_phase=quiz_phase,
        )
        base_clip.unlink(missing_ok=True)

    def _overlay_caption_phrases(
        self,
        base_clip: Path,
        dest: Path,
        *,
        caption_cues: list[tuple[str, float, float]],
        work_dir: Path,
        language: str = "en",
        quiz_card: bool = False,
        quiz_phase: str | None = None,
    ) -> None:
        """Burn Pillow caption PNGs onto a scene clip with timed overlays."""
        ensure_dir(work_dir)
        if not caption_cues:
            shutil.copy2(base_clip, dest)
            return

        from youtube_pipeline.i18n import caption_font_for_language

        font_path = caption_font_for_language(language)
        if quiz_card:
            # Bigger, more centered card for question / answer reveal.
            font_size = max(self._caption_font_size() + 10, int(self.height * 0.045))
            vertical_ratio = 0.42 if (quiz_phase or "") == "question" else 0.48
            max_lines = 5
        else:
            font_size = self._caption_font_size()
            vertical_ratio = 0.68
            max_lines = 2
        # Full-frame transparent PNG; text is drawn around vertical_ratio from the top.
        overlay_size = (self.width, self.height)
        png_paths: list[Path] = []
        for idx, (text, _start, _end) in enumerate(caption_cues):
            rgba = render_caption_rgba(
                text,
                size=overlay_size,
                font_size=font_size,
                font_path=font_path,
                vertical_ratio=vertical_ratio,
                max_lines=max_lines,
                padding_y=22 if quiz_card else 16,
            )
            png = work_dir / f"cap_{idx:02d}.png"
            Image.fromarray(rgba).save(png)
            png_paths.append(png)

        # Overlay each caption PNG for its speech-aligned time window.
        filter_parts: list[str] = []
        current = "[0:v]"
        for idx, (_text, start, end) in enumerate(caption_cues):
            inp = f"[{idx + 1}:v]"
            out = "[v]" if idx == len(caption_cues) - 1 else f"[v{idx}]"
            enable = f"between(t,{start:.3f},{end:.3f})"
            filter_parts.append(
                f"{current}{inp}overlay=0:0:enable='{enable}'{out}"
            )
            current = out

        cmd: list[str] = [self._ffmpeg, "-y", "-i", str(base_clip)]
        for png in png_paths:
            cmd.extend(["-i", str(png)])
        cmd.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[v]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(dest),
            ]
        )
        try:
            self._run(cmd, label="caption-overlay")
        except VideoCompositionError as exc:
            logger.warning("Caption overlay failed (%s); keeping clip without captions", exc)
            shutil.copy2(base_clip, dest)

    def _write_srt(
        self,
        path: Path,
        cues: list[tuple[int, float, float, str]],
    ) -> None:
        lines: list[str] = []
        for index, start, end, text in cues:
            lines.append(str(index))
            lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
            lines.append(text)
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Wrote sidecar subtitles | path=%s | cues=%d", path, len(cues))

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
