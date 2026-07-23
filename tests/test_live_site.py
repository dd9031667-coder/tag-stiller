"""Ручной live-тест: RUN_LIVE_TESTS=1 pytest -m live tests/test_live_site.py."""

import os

import pytest

from app.providers.playwright_provider import PlaywrightCasaMusicaProvider


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_TESTS") != "1",
        reason="live-тест включается только переменной RUN_LIVE_TESTS=1",
    ),
]


def test_example_album_live():
    album = PlaywrightCasaMusicaProvider().fetch_album(
        "https://casa-musica.com/en/music-cd-mp3/716-rimini-open-vol-01.html"
    )
    assert album.title
    assert len(album.tracks) >= 10
