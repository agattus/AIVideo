#!/usr/bin/env python3
"""Generate bundled ambient/oneshot SFX placeholders via ffmpeg lavfi sources."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SFX_ROOT = REPO_ROOT / "assets" / "sfx"
MIN_BYTES = 1024

AMBIENCE_SPECS: dict[str, tuple[str, str]] = {
    "rain": (
        "anoisesrc=color=pink:duration=12",
        "lowpass=f=800,volume=0.4",
    ),
    "wind": (
        "anoisesrc=color=white:duration=12",
        "highpass=f=400,lowpass=f=3000,volume=0.35",
    ),
    "forest": (
        "anoisesrc=color=brown:duration=12",
        "bandpass=f=300:width_type=h:width=600,lowpass=f=2500,volume=0.3",
    ),
    "city": (
        "anoisesrc=color=pink:duration=12",
        "bandpass=f=1200:width_type=h:width=800,highpass=f=200,volume=0.32",
    ),
    "ocean": (
        "anoisesrc=color=pink:duration=12",
        "lowpass=f=500,volume=0.38",
    ),
    "fire": (
        "anoisesrc=color=brown:duration=12",
        "highpass=f=150,lowpass=f=4000,volume=0.33",
    ),
    "night": (
        "anoisesrc=color=blue:duration=12",
        "lowpass=f=300,volume=0.25",
    ),
    "room": (
        "anoisesrc=color=white:duration=12",
        "lowpass=f=600,volume=0.15",
    ),
}

ONESHOT_SPECS: dict[str, tuple[str, str, float]] = {
    "thunder": (
        "anoisesrc=color=brown:duration=1.0",
        "lowpass=f=120,volume=0.7,afade=t=in:st=0:d=0.05,afade=t=out:st=0.7:d=0.3",
        1.0,
    ),
    "footsteps": (
        "sine=frequency=80:duration=0.8",
        "volume=0.5,afade=t=in:st=0:d=0.02,afade=t=out:st=0.5:d=0.3",
        0.8,
    ),
    "door": (
        "sine=frequency=220:duration=0.6",
        "volume=0.45,tremolo=f=8:d=0.6,afade=t=out:st=0.3:d=0.3",
        0.6,
    ),
    "birds": (
        "sine=frequency=2800:duration=0.7",
        "volume=0.35,tremolo=f=25:d=0.5,afade=t=out:st=0.4:d=0.3",
        0.7,
    ),
    "crowd_cheer": (
        "anoisesrc=color=pink:duration=1.2",
        "bandpass=f=1500:width_type=h:width=1000,volume=0.5,afade=t=in:st=0:d=0.08,afade=t=out:st=0.9:d=0.3",
        1.2,
    ),
    "whoosh": (
        "sine=frequency=200:duration=0.9",
        "volume=0.4,asetrate=44100*0.7,aresample=44100,afade=t=in:st=0:d=0.05,afade=t=out:st=0.5:d=0.4",
        0.9,
    ),
}


def resolve_ffmpeg() -> str:
    which = shutil.which("ffmpeg")
    if which:
        return which
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"ffmpeg binary not found: {exc}") from exc


def should_skip(path: Path, force: bool) -> bool:
    return not force and path.is_file() and path.stat().st_size > MIN_BYTES


def run_ffmpeg(ffmpeg: str, lavfi: str, af: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        lavfi,
        "-af",
        af,
        "-ac",
        "1",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"ffmpeg failed for {out.name}: {err[-500:]}")


def generate_pack(force: bool = False) -> list[Path]:
    ffmpeg = resolve_ffmpeg()
    created: list[Path] = []

    for name, (lavfi, af) in AMBIENCE_SPECS.items():
        out = SFX_ROOT / "ambiences" / f"{name}.mp3"
        if should_skip(out, force):
            print(f"skip ambience {name} (exists)")
            continue
        print(f"generate ambience {name}")
        run_ffmpeg(ffmpeg, lavfi, af, out)
        created.append(out)

    for name, (lavfi, af, _dur) in ONESHOT_SPECS.items():
        out = SFX_ROOT / "oneshots" / f"{name}.mp3"
        if should_skip(out, force):
            print(f"skip oneshot {name} (exists)")
            continue
        print(f"generate oneshot {name}")
        run_ffmpeg(ffmpeg, lavfi, af, out)
        created.append(out)

    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate files even when they already exist (>1KB).",
    )
    args = parser.parse_args()
    try:
        generate_pack(force=args.force)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
