import pytest

from app.utils.drop import classify_dropped_paths


def test_classify_html_and_folder(tmp_path):
    html = tmp_path / "album.HTML"
    html.write_text("<html></html>")
    folder = tmp_path / "music"
    folder.mkdir()
    assert classify_dropped_paths([html, folder]) == (
        html.resolve(), folder.resolve(),
    )


def test_classify_rejects_multiple_html_files(tmp_path):
    first = tmp_path / "one.html"
    second = tmp_path / "two.htm"
    first.touch()
    second.touch()
    with pytest.raises(ValueError, match="один HTML"):
        classify_dropped_paths([first, second])


def test_classify_rejects_unsupported_drop(tmp_path):
    image = tmp_path / "cover.jpg"
    image.touch()
    with pytest.raises(ValueError, match="Поддерживаются"):
        classify_dropped_paths([image])
