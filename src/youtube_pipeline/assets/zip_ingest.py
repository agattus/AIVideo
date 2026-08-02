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
# scene_00.jpg | scene_00.jpg_20260801.jpeg | scene_00_foo.png | scene-00.webp
_SCENE_NAME_RE = re.compile(
    r"^scene[_-]?0*(\d+)(?:\.(?:jpe?g|png|webp|bmp)|(?:\.(?:jpe?g|png|webp|bmp))_.+|[_.].+)$",
    re.IGNORECASE,
)
# Strict id extract: scene_01… / scene_01. / scene_01_ — digit boundary prevents scene_1→scene_10
_SCENE_ID_RE = re.compile(r"^scene[_-]?0*(\d+)(?=$|[^0-9])", re.IGNORECASE)
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_WEBP_RIFF = b"RIFF"
_WEBP_WEBP = b"WEBP"


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
        and not p.name.startswith(".")
        and "__MACOSX" not in p.parts
        and _looks_like_image_file(p)
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
    normalize_loose_scene_images(root, expected_scenes=expected_scenes)
    found: list[Path] = []
    missing: list[str] = []
    for scene_id in range(expected_scenes):
        path = find_scene_image(root, scene_id)
        canonical = root / f"scene_{scene_id:02d}.jpg"
        if path is None:
            missing.append(f"scene_{scene_id:02d}.jpg")
            continue
        if path.resolve() != canonical.resolve():
            _normalize_to_jpeg(path, canonical)
            if path != canonical and path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
            path = canonical
        if _looks_blank(path):
            missing.append(f"{path.name} (blank)")
        else:
            found.append(path)

    if missing:
        raise AssetAcquisitionError(
            f"Expected {expected_scenes} scene images; missing/invalid: {', '.join(missing)}"
        )
    if len(found) != expected_scenes:
        raise AssetAcquisitionError(
            f"Image count mismatch: found {len(found)}, expected {expected_scenes}"
        )
    return found


def _iter_scene_candidate_files(assets_dir: Path) -> list[Path]:
    """List image-like ``scene_*`` files in assets/ and one level of subfolders."""
    roots = [assets_dir]
    try:
        for child in assets_dir.iterdir():
            if child.is_dir() and not child.name.startswith((".", "_")):
                roots.append(child)
    except OSError:
        pass

    found: list[Path] = []
    for folder in roots:
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for path in entries:
            if not path.is_file() or path.name.startswith((".", "_")):
                continue
            if _SCENE_ID_RE.match(path.name) is None:
                continue
            if path.stat().st_size <= 256:
                continue
            if _looks_like_image_file(path):
                found.append(path)
    return found


def _scene_id_from_filename(name: str) -> int | None:
    match = _SCENE_ID_RE.match(name)
    return int(match.group(1)) if match else None


def _rank_scene_candidate(path: Path) -> tuple[int, int, str]:
    """Higher is better: real image suffix, then larger file, then stable name."""
    n = path.name.lower()
    score = 0
    if n.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
        score += 3
    if ".jpg" in n or ".jpeg" in n or ".png" in n:
        score += 1
    # Prefer top-level assets/ over nested download folders.
    if path.parent.name.lower() not in {"assets"} and "download" in path.parent.name.lower():
        score -= 1
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return (score, size, n)


def find_scene_image(assets_dir: Path | str, scene_id: int) -> Path | None:
    """Locate a scene image, including oddly named downloads like ``scene_00.jpg_123.jpeg``."""
    root = Path(assets_dir)
    if not root.is_dir():
        return None
    sid = int(scene_id)
    candidates = [
        p for p in _iter_scene_candidate_files(root) if _scene_id_from_filename(p.name) == sid
    ]
    if not candidates:
        return None
    return sorted(candidates, key=_rank_scene_candidate, reverse=True)[0]


def normalize_loose_scene_images(
    assets_dir: Path | str, *, expected_scenes: int | None = None
) -> list[Path]:
    """Rewrite any ``scene_XX*`` image into canonical ``assets/scene_XX.jpg``.

    Runs on Studio reload so Flow/browser downloads like
    ``scene_01.jpg_202608012052.jpeg`` become what the UI expects.
    """
    root = Path(assets_dir)
    if not root.is_dir():
        return []

    by_id: dict[int, list[Path]] = {}
    for path in _iter_scene_candidate_files(root):
        sid = _scene_id_from_filename(path.name)
        if sid is None:
            continue
        by_id.setdefault(sid, []).append(path)

    if expected_scenes is not None:
        scene_ids = list(range(int(expected_scenes)))
    else:
        scene_ids = sorted(by_id)

    written: list[Path] = []
    for sid in scene_ids:
        canonical = root / f"scene_{sid:02d}.jpg"
        candidates = list(by_id.get(sid) or [])
        if not candidates:
            # Still accept an already-canonical file that somehow skipped the scan.
            if canonical.exists() and canonical.stat().st_size > 256:
                written.append(canonical)
            continue

        best = sorted(candidates, key=_rank_scene_candidate, reverse=True)[0]
        canonical_ok = canonical.exists() and canonical.stat().st_size > 256
        if canonical_ok and best.resolve() == canonical.resolve():
            written.append(canonical)
            continue

        # Replace placeholder/canonical with a larger download variant when present.
        replace = (not canonical_ok) or (
            best.resolve() != canonical.resolve()
            and best.stat().st_size > canonical.stat().st_size * 1.15
        )
        if not replace and canonical_ok:
            written.append(canonical)
            # Clean leftover loose clones.
            for extra in candidates:
                if extra.resolve() != canonical.resolve():
                    try:
                        extra.unlink()
                    except OSError:
                        pass
            continue

        src_name = best.name
        _normalize_to_jpeg(best, canonical)
        for extra in candidates:
            if extra.resolve() == canonical.resolve():
                continue
            try:
                extra.unlink()
            except OSError:
                pass
        if canonical.exists() and canonical.stat().st_size > 256:
            written.append(canonical)
            logger.info(
                "Normalized loose scene image | scene=%d | from=%s | to=%s",
                sid,
                src_name,
                canonical.name,
            )
    return written


def _looks_like_image_file(path: Path) -> bool:
    """True if suffix is an image type, name embeds one, or file magic looks like an image."""
    suffix = path.suffix.lower()
    if suffix in _IMAGE_EXTS:
        return True
    name = path.name.lower()
    # Downloaders sometimes produce scene_00.jpg_1234567890
    if any(token in name for token in (".jpg", ".jpeg", ".png", ".webp", ".bmp")):
        return True
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return False
    if head.startswith(_JPEG_MAGIC) or head.startswith(_PNG_MAGIC):
        return True
    if head.startswith(_WEBP_RIFF) and len(head) >= 12 and head[8:12] == _WEBP_WEBP:
        return True
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def _map_images_to_scenes(images: list[Path], *, expected_scenes: int) -> dict[int, Path]:
    """Prefer explicit scene_XX names; otherwise assign sorted order 0..N-1."""
    numbered: list[tuple[int, Path]] = []
    unmatched: list[Path] = []
    for path in images:
        match = _SCENE_NAME_RE.match(path.name)
        if match:
            numbered.append((int(match.group(1)), path))
            continue
        # stem may be scene_00 for scene_00.jpg_12345 (suffix=.jpg_12345)
        match = _SCENE_RE.search(path.stem)
        if not match:
            # Fall back to full name for weird suffixes.
            match = re.search(r"scene[_-]?0*(\d+)", path.name, re.IGNORECASE)
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
