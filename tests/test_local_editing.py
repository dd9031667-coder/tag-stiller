from pathlib import Path

from app.models import LocalAudioFile, MatchStatus
from app.services.local_editing import build_local_editing_session


class FakeReader:
    def __init__(self, values):
        self.values = values

    def read_current(self, path):
        return self.values[Path(path).name]


def test_local_session_uses_existing_tags():
    files = [
        LocalAudioFile(Path("01 - Old.mp3"), None, 1, 120, "Artist", "Title"),
        LocalAudioFile(Path("02 - Other.mp3"), None, 2, 130, "", ""),
    ]
    reader = FakeReader({
        "01 - Old.mp3": {
            "track_number": "1/2", "title": "Song (Tango 32)",
            "artist": "Singer", "album": "Album", "album_artist": "Various",
            "year": "2024", "album_label": "Label",
        },
        "02 - Other.mp3": {"track_number": "2", "title": "Other"},
    })
    album, matches = build_local_editing_session(files, reader)
    assert album.title == "Album"
    assert album.album_artist == "Various"
    assert album.album_label == "Label"
    assert album.year == "2024"
    assert matches[0].track.title == "Song"
    assert matches[0].track.dance_style == "Tango"
    assert matches[0].track.dance_tempo == "32"
    assert all(match.status is MatchStatus.GREEN for match in matches)


def test_local_session_marks_missing_and_duplicate_numbers():
    files = [
        LocalAudioFile(Path("untagged.mp3"), None, None),
        LocalAudioFile(Path("01 duplicate.mp3"), None, 1),
    ]
    reader = FakeReader({
        "untagged.mp3": {},
        "01 duplicate.mp3": {},
    })
    _, matches = build_local_editing_session(files, reader)
    assert all(match.status is MatchStatus.YELLOW for match in matches)
    assert "назначен по порядку" in matches[0].note
    assert "повторяется" in matches[1].note
    assert matches[0].track.title == "untagged"


def test_local_session_uses_plain_folder_as_album_name():
    files = [
        LocalAudioFile(Path("/music/My Album/01 Song.mp3"), None, 1),
    ]
    reader = FakeReader({"01 Song.mp3": {}})
    album, matches = build_local_editing_session(files, reader)
    assert album.title == "My Album"
    assert matches[0].track.album == "My Album"


def test_local_session_parses_formatted_folder_metadata():
    files = [
        LocalAudioFile(
            Path("/music/Prandi Records - Rimini Open (2000)/01 Song.mp3"),
            None, 1,
        ),
    ]
    reader = FakeReader({"01 Song.mp3": {}})
    album, matches = build_local_editing_session(files, reader)
    assert album.title == "Rimini Open"
    assert album.album_label == "Prandi Records"
    assert album.year == "2000"
    assert matches[0].track.album == "Rimini Open"
    assert matches[0].track.album_label == "Prandi Records"
    assert matches[0].track.year == "2000"
