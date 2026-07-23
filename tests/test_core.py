from pathlib import Path

import pytest

from app.audio.scanner import extract_track_position
from app.matching import match_tracks
from app.models import AlbumMetadata, LocalAudioFile, MatchStatus, TrackMetadata
from app.providers.html_parser import CasaMusicaHtmlParser
from app.utils.text import normalize_text, split_title_dance_suffix


@pytest.mark.parametrize(("name", "expected"), [
    ("01 - Song Name.mp3", (None, 1)),
    ("1. Song Name.flac", (None, 1)),
    ("01_Song_Name.m4a", (None, 1)),
    ("Track 01 - Song Name.mp3", (None, 1)),
    ("CD1-01 Song Name.mp3", (1, 1)),
    ("1-01 Song Name.flac", (1, 1)),
    ("no number.mp3", (None, None)),
])
def test_extract_track_position(name, expected):
    assert extract_track_position(name) == expected


def test_normalize_title():
    assert normalize_text("  L’Été—Bleu!! ") == normalize_text("l'ete - bleu")


def test_fixture_parser():
    html = Path("tests/fixtures/casa_album.html").read_text()
    album = CasaMusicaHtmlParser().parse(html, "https://example.test")
    assert album.title == "Rimini Open Vol. 01"
    assert album.album_artist == "Prandi Sound Orchestra"
    assert album.year == "2000"
    assert len(album.tracks) == 3
    assert album.tracks[0].title == "Spring"
    assert album.tracks[0].dance_style == "Slow Waltz"
    assert album.tracks[0].dance_tempo == "29"
    assert album.tracks[0].duration_seconds == 184
    assert album.tracks[2].disc_number == 3
    assert album.tracks[2].track_number == 4


@pytest.mark.parametrize(("source", "expected"), [
    ("Spring (Slow Waltz 29)", ("Spring", "Slow Waltz", "29")),
    ("Blue Moon (Slowfox 29 BPM)", ("Blue Moon", "Slowfox", "29")),
    ("Tango canción (Tango 32,5)", ("Tango canción", "Tango", "32.5")),
    ("Song (Live)", ("Song (Live)", "", "")),
])
def test_split_title_dance_suffix(source, expected):
    assert split_title_dance_suffix(source) == expected


def _track(number=1, duration=100.0, title="Song"):
    return TrackMetadata(None, number, title, duration_seconds=duration)


def test_match_by_number_and_duration():
    album = AlbumMetadata("Album", [_track()])
    local = LocalAudioFile(Path("01 Song.mp3"), None, 1, 103.5, "", "")
    match = match_tracks(album, [local], 4)[0]
    assert match.status is MatchStatus.GREEN


def test_duration_mismatch_is_yellow():
    album = AlbumMetadata("Album", [_track()])
    local = LocalAudioFile(Path("01 Song.mp3"), None, 1, 118, "", "")
    match = match_tracks(album, [local], 4)[0]
    assert match.status is MatchStatus.YELLOW
    assert match.duration_difference == 18


def test_duplicates_are_red():
    album = AlbumMetadata("Album", [_track()])
    files = [
        LocalAudioFile(Path("01 A.mp3"), None, 1),
        LocalAudioFile(Path("01 B.mp3"), None, 1),
    ]
    match = match_tracks(album, files)[0]
    assert match.status is MatchStatus.RED
    assert match.local_file is None


def test_missing_number_not_matched():
    album = AlbumMetadata("Album", [_track()])
    local = LocalAudioFile(Path("Song.mp3"), None, None)
    assert match_tracks(album, [local])[0].status is MatchStatus.RED
