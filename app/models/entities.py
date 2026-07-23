from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class MatchStatus(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass(slots=True)
class TrackMetadata:
    disc_number: int | None
    track_number: int
    title: str
    artist: str = ""
    language: str = ""
    dance_style: str = ""
    dance_tempo: str = ""
    duration_seconds: float | None = None
    album: str = ""
    album_artist: str = ""
    year: str = ""
    source_url: str = ""


@dataclass(slots=True)
class AlbumMetadata:
    title: str
    tracks: list[TrackMetadata] = field(default_factory=list)
    album_artist: str = ""
    year: str = ""
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AlbumMetadata":
        tracks = [TrackMetadata(**item) for item in data.get("tracks", [])]
        return cls(
            title=data.get("title", ""),
            tracks=tracks,
            album_artist=data.get("album_artist", ""),
            year=str(data.get("year", "") or ""),
            source_url=data.get("source_url", ""),
        )


@dataclass(slots=True)
class LocalAudioFile:
    path: Path
    disc_number: int | None
    track_number: int | None
    duration_seconds: float | None = None
    artist: str = ""
    title: str = ""


@dataclass(slots=True)
class TrackMatch:
    track: TrackMetadata
    local_file: LocalAudioFile | None
    status: MatchStatus
    note: str = ""
    duration_difference: float | None = None
    enabled: bool = True


@dataclass(slots=True)
class TagChange:
    field: str
    old_value: Any
    new_value: Any


@dataclass(slots=True)
class BackupRecord:
    path: str
    format: str
    tags: dict[str, Any]
    created_at: str

