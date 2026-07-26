"""Unzip and validate manually uploaded scene images."""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

from PIL import Image

from youtube_pipeline.exceptions import AssetAcquisitionError
from youtube_pipeline.utils.files import ensure_dir
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_SCENE_RE = re.compile(r"(?:scene[_-]?)?(\d+)", re.IGNORECASE)


def ingest_assets_zip(
    zip_path: Path | str,
    assets_dir: Path | str,
    *,
    expected_scenes: int,
) -> list[Path]:
    """Extract ``zip_path`` into ``assets_dir`` as ``scene_XX.jpg`` files."""
    zpath = Path(zip_path)
    if not zpath.exists():
        raise AssetAcquisitionError(f"ZIP not found: {zpath}")
    if not zipfile.is_zipfile(zpath):
        raise AssetAcquisitionError(f"Not a valid ZIP archive: {zpath}")

    dest = ensure_dir(Path(assets_dir))
    extract_root = ensure_dir(dest / "_zip_extract")
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zpath, "r") as zf:
        zf.extractall(extract_root)

    images = [
        p
        for p in sorted(extract_root.rglob("*"))
        if p.is_file()
        and p.suffix.lower() in _IMAGE_EXTS
        and not p.name.startswith(".")
        and "__MACOSX" not in p.parts
    ]
    if not images:
        raise AssetAcquisitionError("ZIP contained no image files (.jpg/.png/.webp)")

    mapped = _map_images_to_scenes(images, expected_scenes=expected_scenes)
    written: list[Path] = []
    for scene_id, src in mapped.items():
        out = dest / f"scene_{scene_id:02d}.jpg"
        _normalize_to_jpeg(src, out)
        written.append(out)
        logger.info("Ingested upload | scene=%d | from=%s | to=%s", scene_id, src.name, out)

    shutil.rmtree(extract_root, ignore_errors=True)
    validate_scene_images(dest, expected_scenes=expected_scenes)
    return written


def validate_scene_images(assets_dir: Path | str, *, expected_scenes: int) -> list[Path]:
    """Ensure ``scene_00.jpg`` … ``scene_{N-1:02d}.jpg`` exist and are non-blank."""
    root = Path(assets_dir)
    found: list[Path] = []
    missing: list[str] = []
    for scene_id in range(expected_scenes):
        path = root / f"scene_{scene_id:02d}.jpg"
        # Also accept .png that user dropped without conversion.
        alt = root / f"scene_{scene_id:02d}.png"
        if path.exists() and path.stat().st_size > 256:
            if _looks_blank(path):
                missing.append(f"{path.name} (blank)")
            else:
                found.append(path)
        elif alt.exists() and alt.stat().st_size > 256:
            _normalize_to_jpeg(alt, path)
            found.append(path)
        else:
            missing.append(f"scene_{scene_id:02d}.jpg")

    if missing:
        raise AssetAcquisitionError(
            f"Expected {expected_scenes} scene images; missing/invalid: {', '.join(missing)}"
        )
    if len(found) != expected_scenes:
        raise AssetAcquisitionError(
            f"Image count mismatch: found {len(found)}, expected {expected_scenes}"
        )
    return found


def _map_images_to_scenes(images: list[Path], *, expected_scenes: int) -> dict[int, Path]:
    """Prefer explicit scene_XX names; otherwise assign sorted order 0..N-1."""
    numbered: list[tuple[int, Path]] = []
    unmatched: list[Path] = []
    for path in images:
        match = _SCENE_RE.search(path.stem)
        if not match:
            unmatched.append(path)
            continue
        numbered.append((int(match.group(1)), path))

    by_id: dict[int, Path] = {}
    if numbered:
        nums = {n for n, _ in numbered}
        one_based = 0 not in nums and all(1 <= n <= expected_scenes for n in nums)
        for n, path in numbered:
            scene_id = (n - 1) if one_based else n
            if 0 <= scene_id < expected_scenes and scene_id not in by_id:
                by_id[scene_id] = path
            else:
                unmatched.append(path)

    if len(by_id) == expected_scenes:
        return by_id

    remaining = [i for i in range(expected_scenes) if i not in by_id]
    unmatched_sorted = sorted(unmatched, key=lambda p: p.name.lower())
    for scene_id, path in zip(remaining, unmatched_sorted, strict=False):
        by_id[scene_id] = path

    if len(by_id) != expected_scenes:
        raise AssetAcquisitionError(
            f"ZIP has {len(images)} images but script expects {expected_scenes} scenes"
        )
    return by_id


def _normalize_to_jpeg(src: Path, dest: Path) -> None:
    try:
        with Image.open(src) as img:
            img.convert("RGB").save(dest, format="JPEG", quality=92)
    except Exception:
        # Last resort: copy raw bytes under .jpg name.
        shutil.copy2(src, dest)


def _looks_blank(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            sample = img.convert("RGB").resize((32, 32))
            pixels = list(sample.getdata())
        if not pixels:
            return True
        avg = sum(sum(p) for p in pixels) / (len(pixels) * 3.0)
        return avg < 8.0
    except Exception:  # noqa: BLE001
        return True
