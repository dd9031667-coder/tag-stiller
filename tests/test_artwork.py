import pytest

from app.audio.artwork import (
    cover_from_value, cover_to_json, find_cover_image, load_cover_image,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"
JPEG = b"\xff\xd8\xff\xe0" + b"test-image"


def test_find_cover_case_insensitive(tmp_path):
    cover = tmp_path / "COVER.JpG"
    cover.write_bytes(JPEG)
    assert find_cover_image(tmp_path) == cover


def test_find_cover_ignores_unrelated_images(tmp_path):
    (tmp_path / "front.jpg").write_bytes(JPEG)
    assert find_cover_image(tmp_path) is None


def test_multiple_covers_are_rejected(tmp_path):
    (tmp_path / "cover.jpg").write_bytes(JPEG)
    (tmp_path / "cover.png").write_bytes(PNG)
    with pytest.raises(ValueError, match="несколько"):
        find_cover_image(tmp_path)


def test_load_and_json_roundtrip(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(PNG)
    loaded = load_cover_image(cover)
    assert loaded["mime"] == "image/png"
    assert cover_from_value(cover_to_json(loaded)) == ("image/png", PNG)


def test_invalid_cover_is_rejected(tmp_path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="JPEG"):
        load_cover_image(cover)
