import json
from pathlib import Path

from app.audio.tags import TagOptions
from app.audio.tags import TagService
from app.models import AlbumMetadata, LocalAudioFile, MatchStatus, TrackMatch, TrackMetadata
from app.services.album_io import (
    load_album_json, save_album_json, update_album_details, update_album_title,
)
from app.services.backup import BackupService
from app.services.tagging import build_change_plan


def _match():
    track = TrackMetadata(
        None, 1, "New title", "New artist", "english", "Slow Waltz", "29",
        100, "Album", "Album Artist", "2000", "url", "Record Label",
    )
    local = LocalAudioFile(Path("01.mp3"), None, 1)
    return TrackMatch(track, local, MatchStatus.GREEN)


def test_change_plan_keeps_empty_by_default():
    match = _match()
    match.track.language = ""
    changes = build_change_plan(match, {"language": "german", "title": "Old"}, TagOptions())
    fields = {change.field for change in changes}
    assert "language" not in fields
    assert "title" in fields
    assert "album" in fields
    assert "album_label" in fields
    assert "dance_tempo" in fields
    assert "genre" not in fields


def test_change_plan_optional_genre():
    changes = build_change_plan(_match(), {}, TagOptions(write_style_to_genre=True))
    assert any(change.field == "genre" for change in changes)


def test_album_json_roundtrip(tmp_path):
    album = AlbumMetadata("A", [_match().track], "AA", "2000", "url", "Label")
    target = tmp_path / "album.json"
    save_album_json(album, target)
    loaded = load_album_json(target)
    assert loaded == album


def test_update_album_title_propagates_to_tracks():
    album = AlbumMetadata("Old", [_match().track])
    update_album_title(album, " New Album ")
    assert album.title == "New Album"
    assert album.tracks[0].album == "New Album"


def test_update_album_details_propagates_metadata():
    album = AlbumMetadata("Old", [_match().track])
    update_album_details(
        album, title="New", album_artist="Various Artists",
        year="2024", album_label="Casa musica",
    )
    assert album.album_artist == album.tracks[0].album_artist == "Various Artists"
    assert album.year == album.tracks[0].year == "2024"
    assert album.album_label == album.tracks[0].album_label == "Casa musica"


class FakeTags:
    def __init__(self):
        self.writes = []

    def read_current(self, path):
        return {"title": "Original", "dance_tempo": "28"}

    def write_atomic(self, path, values):
        self.writes.append((Path(path), values))


def test_backup_serialization_and_restore(tmp_path):
    audio = tmp_path / "01.mp3"
    audio.write_bytes(b"fake")
    destination = tmp_path / "backup.json"
    fake = FakeTags()
    service = BackupService(fake)
    records = service.create([audio], destination)
    assert records[0].tags["title"] == "Original"
    assert json.loads(destination.read_text())["version"] == 1
    restored, errors = service.restore(destination)
    assert errors == []
    assert restored == [str(audio.resolve())]
    assert fake.writes[0][1]["dance_tempo"] == "28"


def test_backup_path_remap(tmp_path):
    old = tmp_path / "old.mp3"
    new = tmp_path / "new.mp3"
    old.write_bytes(b"fake")
    backup_path = tmp_path / "backup.json"
    service = BackupService(FakeTags())
    service.create([old], backup_path)
    old.rename(new)

    service.remap_paths(backup_path, {str(old): str(new)})
    records = service.load(backup_path)
    assert records[0].path == str(new.resolve())


def test_mp3_tag_write_and_restore(tmp_path):
    from mutagen.id3 import APIC, ID3, TIT2, TPUB

    audio = tmp_path / "01.mp3"
    original_cover = b"\xff\xd8\xff\xe0original-cover"
    replacement_cover = b"\x89PNG\r\n\x1a\nreplacement-cover"
    initial = ID3()
    initial.add(TIT2(encoding=3, text=["Original"]))
    initial.add(TPUB(encoding=3, text=["Original Label"]))
    initial.add(APIC(
        encoding=3, mime="image/jpeg", type=3, desc="Cover",
        data=original_cover,
    ))
    initial.save(audio)
    tags = TagService()
    backup = BackupService(tags)
    backup_path = tmp_path / "backup.json"
    backup.create([audio], backup_path)

    tags.write_atomic(audio, {
        "title": "Changed",
        "dance_tempo": "29",
        "album_label": "New Label",
        "cover_art": {"mime": "image/png", "data": replacement_cover},
    })
    assert tags.read_current(audio)["title"] == "Changed"
    assert tags.read_current(audio)["dance_tempo"] == "29"
    assert tags.read_current(audio)["album_label"] == "New Label"
    assert tags.read_cover(audio) == {
        "mime": "image/png", "data": replacement_cover,
    }

    restored, errors = backup.restore(backup_path)
    assert errors == []
    assert restored == [str(audio.resolve())]
    assert tags.read_current(audio)["title"] == "Original"
    assert tags.read_current(audio)["dance_tempo"] == ""
    assert tags.read_current(audio)["album_label"] == "Original Label"
    assert tags.read_cover(audio) == {
        "mime": "image/jpeg", "data": original_cover,
    }
