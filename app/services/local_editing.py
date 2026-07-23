from __future__ import annotations

import re
from collections import Counter
from typing import Protocol

from app.audio.scanner import extract_title_hint
from app.models import (
    AlbumMetadata, LocalAudioFile, MatchStatus, TrackMatch, TrackMetadata,
)
from app.utils.text import split_title_dance_suffix


class TagReader(Protocol):
    def read_current(self, path) -> dict: ...


def _number(value, fallback: int | None = None) -> int | None:
    match = re.match(r"\s*(\d+)", str(value or ""))
    return int(match.group(1)) if match else fallback


def _first(values: list[dict], field: str) -> str:
    return next((str(item.get(field, "")).strip() for item in values if item.get(field)), "")


def build_local_editing_session(
    files: list[LocalAudioFile],
    tag_reader: TagReader,
) -> tuple[AlbumMetadata, list[TrackMatch]]:
    """Создать редактируемый альбом без внешнего источника метаданных."""
    current_tags = [tag_reader.read_current(local.path) for local in files]
    album_title = _first(current_tags, "album")
    album_artist = _first(current_tags, "album_artist")
    album_label = _first(current_tags, "album_label")
    year = _first(current_tags, "year")

    tracks: list[TrackMetadata] = []
    assigned_by_order: set[int] = set()
    for index, (local, current) in enumerate(zip(files, current_tags, strict=True), start=1):
        track_number = _number(current.get("track_number"), local.track_number)
        if track_number is None:
            track_number = index
            assigned_by_order.add(index - 1)
        disc_number = _number(current.get("disc_number"), local.disc_number)
        raw_title = str(current.get("title") or local.title or extract_title_hint(local.path.name))
        title, style_from_title, tempo_from_title = split_title_dance_suffix(raw_title)
        tracks.append(TrackMetadata(
            disc_number=disc_number,
            track_number=track_number,
            title=title,
            artist=str(current.get("artist") or local.artist or ""),
            language=str(current.get("language") or ""),
            dance_style=str(current.get("dance_style") or style_from_title),
            dance_tempo=str(current.get("dance_tempo") or tempo_from_title),
            duration_seconds=local.duration_seconds,
            album=str(current.get("album") or album_title),
            album_artist=str(current.get("album_artist") or album_artist),
            year=str(current.get("year") or year),
            album_label=str(current.get("album_label") or album_label),
        ))

    counts = Counter((track.disc_number or 1, track.track_number) for track in tracks)
    matches: list[TrackMatch] = []
    for index, (track, local) in enumerate(zip(tracks, files, strict=True)):
        notes: list[str] = ["Локальный режим"]
        status = MatchStatus.GREEN
        if index in assigned_by_order:
            status = MatchStatus.YELLOW
            notes.append("Номер назначен по порядку — проверьте")
        if counts[(track.disc_number or 1, track.track_number)] > 1:
            status = MatchStatus.YELLOW
            notes.append("Номер повторяется — исправьте вручную")
        matches.append(TrackMatch(
            track=track,
            local_file=local,
            status=status,
            note="; ".join(notes),
        ))

    album = AlbumMetadata(
        title=album_title,
        tracks=tracks,
        album_artist=album_artist,
        year=year,
        album_label=album_label,
    )
    return album, matches
