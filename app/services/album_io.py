from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from app.models import AlbumMetadata


def update_album_title(album: AlbumMetadata, title: str) -> None:
    """Синхронизировать название альбома в контейнере и во всех треках."""
    album.title = title.strip()
    for track in album.tracks:
        track.album = album.title


def save_album_json(album: AlbumMetadata, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(album.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_album_json(path: str | Path) -> AlbumMetadata:
    return AlbumMetadata.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def export_album_csv(album: AlbumMetadata, path: str | Path) -> None:
    fields = list(asdict(album.tracks[0]).keys()) if album.tracks else [
        "disc_number", "track_number", "title", "artist", "language",
        "dance_style", "dance_tempo", "duration_seconds", "album",
        "album_artist", "year", "source_url",
    ]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(track) for track in album.tracks)
