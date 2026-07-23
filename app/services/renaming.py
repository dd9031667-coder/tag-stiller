from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from app.models import TrackMetadata


DEFAULT_RENAME_TEMPLATE = "{disc_prefix}{track:02d} - {artist} - {title}"
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def sanitize_filename_component(value: str) -> str:
    """Сделать имя переносимым между Windows и macOS."""
    value = unicodedata.normalize("NFC", value)
    value = _INVALID.sub("_", value)
    value = re.sub(r"\s+", " ", value).strip().rstrip(". ")
    if not value:
        return "Без названия"
    if value.split(".", 1)[0].upper() in _RESERVED:
        value = f"_{value}"
    return value[:220].rstrip(". ")


def build_audio_filename(
    track: TrackMetadata,
    extension: str,
    template: str = DEFAULT_RENAME_TEMPLATE,
) -> str:
    values = {
        "disc": track.disc_number or 1,
        "disc_prefix": f"{track.disc_number}-" if track.disc_number else "",
        "track": track.track_number,
        "artist": track.artist,
        "title": track.title,
        "album": track.album,
        "year": track.year,
    }
    try:
        stem = template.format_map(values)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Некорректный шаблон переименования: {exc}") from exc
    suffix = extension if extension.startswith(".") else f".{extension}"
    return f"{sanitize_filename_component(stem)}{suffix.lower()}"


def rename_audio_file(
    source: str | Path,
    track: TrackMetadata,
    template: str = DEFAULT_RENAME_TEMPLATE,
) -> Path:
    source_path = Path(source)
    target = source_path.with_name(build_audio_filename(track, source_path.suffix, template))
    if source_path == target:
        return source_path
    if target.exists():
        raise FileExistsError(f"Файл с именем «{target.name}» уже существует.")
    os.rename(source_path, target)
    return target
