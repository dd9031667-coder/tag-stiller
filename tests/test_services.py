import json
from pathlib import Path

from app.audio.tags import TagOptions
from app.audio.tags import TagService
from app.models import AlbumMetadata, LocalAudioFile, MatchStatus, TrackMatch, TrackMetadata
from app.services.album_io import load_album_json, save_album_json
from app.services.backup import BackupService
from app.services.tagging import build_change_plan


def _match():
    track = TrackMetadata(
        None, 1, "New title", "New artist", "english", "Slow Waltz", "29",
        100, "Album", "Album Artist", "2000", "url",
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
    assert "dance_tempo" in fields
    assert "genre" not in fields


def test_change_plan_optional_genre():
    changes = build_change_plan(_match(), {}, TagOptions(write_style_to_genre=True))
    assert any(change.field == "genre" for change in changes)


def test_album_json_roundtrip(tmp_path):
    album = AlbumMetadata("A", [_match().track], "AA", "2000", "url")
    target = tmp_path / "album.json"
    save_album_json(album, target)
    loaded = load_album_json(target)
    assert loaded == album


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


def test_mp3_tag_write_and_restore(tmp_path):
    from mutagen.id3 import ID3, TIT2

    audio = tmp_path / "01.mp3"
    initial = ID3()
    initial.add(TIT2(encoding=3, text=["Original"]))
    initial.save(audio)
    tags = TagService()
    backup = BackupService(tags)
    backup_path = tmp_path / "backup.json"
    backup.create([audio], backup_path)

    tags.write_atomic(audio, {"title": "Changed", "dance_tempo": "29"})
    assert tags.read_current(audio)["title"] == "Changed"
    assert tags.read_current(audio)["dance_tempo"] == "29"

    restored, errors = backup.restore(backup_path)
    assert errors == []
    assert restored == [str(audio.resolve())]
    assert tags.read_current(audio)["title"] == "Original"
    assert tags.read_current(audio)["dance_tempo"] == ""
