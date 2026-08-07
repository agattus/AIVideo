from io import BytesIO

from PIL import Image

from youtube_pipeline.assets.image_aspect import (
    aspect_prompt_clause,
    normalize_image_to_aspect,
    target_size,
)


def test_target_size_vertical():
    w, h = target_size("9:16", long_edge=1280)
    assert h > w
    assert abs((h / w) - (16 / 9)) < 0.02


def test_normalize_crops_landscape_to_portrait():
    img = Image.new("RGB", (1600, 900), color=(20, 20, 20))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    out = normalize_image_to_aspect(buf.getvalue(), "9:16")
    result = Image.open(BytesIO(out))
    assert result.height > result.width
    assert abs((result.height / result.width) - (16 / 9)) < 0.05


def test_aspect_prompt_mentions_vertical():
    clause = aspect_prompt_clause("9:16")
    assert "9:16" in clause or "vertical" in clause.lower()
