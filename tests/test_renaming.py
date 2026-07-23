from pathlib import Path

import pytest

from app.models import TrackMetadata
from app.services.renaming import (
    build_audio_filename, rename_audio_file, sanitize_filename_component,
)


def _track(**kwargs):
    values = {
        "disc_number": None, "track_number": 3, "title": "My Song",
        "artist": "The Artist", "album": "Album",
    }
    values.update(kwargs)
    return TrackMetadata(**values)


def test_build_filename_preserves_extension_and_track_padding():
    assert build_audio_filename(_track(), ".FLAC") == "03 - The Artist - My Song.flac"


def test_build_filename_with_disc_and_custom_template():
    track = _track(disc_number=2)
    assert build_audio_filename(track, ".mp3", "{disc}-{track:02d} {title}") == "2-03 My Song.mp3"


def test_sanitize_windows_filename():
    assert sanitize_filename_component(' A/B: "Song"? ') == "A_B_ _Song__"
    assert sanitize_filename_component("CON") == "_CON"


def test_rename_audio_file_and_collision(tmp_path):
    source = tmp_path / "old.MP3"
    source.write_bytes(b"audio")
    renamed = rename_audio_file(source, _track())
    assert renamed.name == "03 - The Artist - My Song.mp3"
    assert renamed.read_bytes() == b"audio"

    another = tmp_path / "another.mp3"
    another.write_bytes(b"other")
    with pytest.raises(FileExistsError):
        rename_audio_file(another, _track())
