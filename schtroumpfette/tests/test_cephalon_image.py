import base64
import io

import pytest
from PIL import Image

from cephalon import image as image_module
from cephalon.image import ImageError, prepare


def encoded(size, mode="RGB", format="PNG", **kwargs) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, "purple").save(buffer, format=format, **kwargs)
    return buffer.getvalue()


def decoded(prepared) -> Image.Image:
    return Image.open(io.BytesIO(base64.standard_b64decode(prepared.data)))


def test_small_capture_is_kept_as_png():
    prepared = prepare(encoded((1920, 1080)))
    assert prepared.media_type == "image/png" and prepared.original == prepared.size == (1920, 1080)
    assert decoded(prepared).size == (1920, 1080) and "\n" not in prepared.data
    assert prepared.summary().startswith("1920x1080, PNG ")
    assert prepared.block() == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": prepared.data}}


def test_4k_capture_is_reduced():
    prepared = prepare(encoded((3840, 2160), format="JPEG"))
    assert prepared.original == (3840, 2160) and prepared.size == (2576, 1449) and decoded(prepared).size == (2576, 1449)
    assert prepared.summary().startswith("3840x2160 → 2576x1449, PNG")


def test_heavy_capture_goes_to_jpeg(monkeypatch):
    monkeypatch.setattr(image_module, "IMAGE_PNG_LIMIT", 100)
    prepared = prepare(encoded((800, 600), mode="RGBA"))
    assert prepared.media_type == "image/jpeg" and decoded(prepared).format == "JPEG"


def test_gif_keeps_its_first_frame():
    buffer = io.BytesIO()
    frames = [Image.new("P", (40, 30), color) for color in (1, 2)]
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])
    prepared = prepare(buffer.getvalue())
    assert prepared.size == (40, 30) and prepared.media_type == "image/png"


@pytest.mark.parametrize("data", [b"pas une image", encoded((10, 10))[:40], b""])
def test_unreadable_image(data):
    with pytest.raises(ImageError, match="image illisible"):
        prepare(data)
