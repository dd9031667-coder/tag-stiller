import re
from pathlib import Path

import pytest

from app.audio.scanner import extract_title_hint, extract_track_position
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


@pytest.mark.parametrize(("name", "expected"), [
    ("01 - Song Name.mp3", "Song Name"),
    ("Track 01 - Song_Name.mp3", "Song Name"),
    ("CD1-01 Song Name.mp3", "Song Name"),
    ("1-01 Song Name.flac", "Song Name"),
])
def test_extract_title_hint(name, expected):
    assert extract_title_hint(name) == expected


def test_normalize_title():
    assert normalize_text("  L’Été—Bleu!! ") == normalize_text("l'ete - bleu")


def test_fixture_parser():
    html = Path("tests/fixtures/casa_album.html").read_text()
    album = CasaMusicaHtmlParser().parse(html, "https://example.test")
    assert album.title == "Rimini Open Vol. 01"
    assert album.album_artist == "Prandi Sound Orchestra"
    assert album.album_label == "Prandi Sound Records"
    assert album.year == "2000"
    assert len(album.tracks) == 3
    assert album.tracks[0].title == "Spring"
    assert album.tracks[0].dance_style == "Slow Waltz"
    assert album.tracks[0].dance_tempo == "29"
    assert album.tracks[0].album_artist == "Prandi Sound Orchestra"
    assert album.tracks[0].album_label == "Prandi Sound Records"
    assert album.tracks[0].duration_seconds == 184
    assert album.tracks[2].disc_number == 3
    assert album.tracks[2].track_number == 4


@pytest.mark.parametrize(("head", "expected"), [
    (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"Rimini Open Vol. 01"}</script>',
        "Rimini Open Vol. 01",
    ),
    (
        '<meta property="og:title" content="Casa musica - Rimini Open Vol. 01">',
        "Rimini Open Vol. 01",
    ),
    (
        "<title>Rimini Open Vol. 01 - Casa musica</title>",
        "Rimini Open Vol. 01",
    ),
])
def test_album_title_fallbacks(head, expected):
    fixture = Path("tests/fixtures/casa_album.html").read_text()
    fixture = re.sub(r"<h1>.*?</h1>", "", fixture)
    fixture = fixture.replace("<html>", f"<html><head>{head}</head>")
    album = CasaMusicaHtmlParser().parse(fixture)
    assert album.title == expected
    assert all(track.album == expected for track in album.tracks)


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
