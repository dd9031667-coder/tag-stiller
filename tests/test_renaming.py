from pathlib import Path

import pytest

from app.models import TrackMetadata
from app.services.renaming import (
    album_folder_target, build_album_folder_name, build_audio_filename,
    rename_album_folder, rename_audio_file, sanitize_filename_component,
)
from app.models import AlbumMetadata


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


def test_build_and_rename_album_folder(tmp_path):
    source = tmp_path / "old album"
    source.mkdir()
    (source / "track.mp3").write_bytes(b"audio")
    album = AlbumMetadata(
        "Rimini Open Vol. 01", album_artist="Prandi Sound Orchestra",
        year="2000", album_label="Prandi Sound Records",
    )
    assert build_album_folder_name(
        album, "{label} - {album} ({year})",
    ) == (
        "Prandi Sound Records - Rimini Open Vol. 01 (2000)"
    )
    expected = tmp_path / "Prandi Sound Records - Rimini Open Vol. 01 (2000)"
    assert album_folder_target(
        source, album, "{label} - {album} ({year})",
    ) == expected
    renamed = rename_album_folder(
        source, album, "{label} - {album} ({year})",
    )
    assert renamed == expected
    assert (renamed / "track.mp3").read_bytes() == b"audio"


def test_album_folder_collision_is_rejected(tmp_path):
    source = tmp_path / "old"
    source.mkdir()
    album = AlbumMetadata("Album", year="2024", album_label="Label")
    album_folder_target(source, album).mkdir()
    with pytest.raises(FileExistsError):
        rename_album_folder(source, album)


def test_build_album_folder_as_title_and_year():
    album = AlbumMetadata(
        "Rimini Open Vol. 01",
        year="2000",
        album_label="Prandi Sound Records",
    )
    assert build_album_folder_name(
        album, "{album} - {year}",
    ) == "Rimini Open Vol. 01 - 2000"


def test_title_and_year_format_handles_missing_year():
    album = AlbumMetadata("Rimini Open Vol. 01")
    assert build_album_folder_name(album, "{album}") == "Rimini Open Vol. 01"


def test_album_folder_template_supports_album_artist():
    album = AlbumMetadata(
        "Rimini Open Vol. 01",
        album_artist="Prandi Sound Orchestra",
        year="2000",
    )
    assert build_album_folder_name(
        album, "{album_artist} - {album} - {year}",
    ) == "Prandi Sound Orchestra - Rimini Open Vol. 01 - 2000"


def test_unknown_album_folder_placeholder_is_rejected():
    with pytest.raises(ValueError, match="Некорректный шаблон"):
        build_album_folder_name(AlbumMetadata("Album"), "{unknown}")
