from __future__ import annotations

from app.audio.tags import TagOptions
from app.models import TagChange, TrackMatch


def desired_values(match: TrackMatch) -> dict[str, str | int]:
    track = match.track
    values: dict[str, str | int] = {
        "track_number": track.track_number,
        "disc_number": track.disc_number or "",
        "artist": track.artist,
        "title": track.title,
        "album": track.album,
        "album_artist": track.album_artist,
        "language": track.language,
        "dance_style": track.dance_style,
        "dance_tempo": track.dance_tempo,
        "year": track.year,
    }
    return values


def build_change_plan(
    match: TrackMatch,
    current: dict[str, str | int],
    options: TagOptions,
) -> list[TagChange]:
    wanted = desired_values(match)
    enabled = options.enabled_fields()
    changes: list[TagChange] = []
    for field, new_value in wanted.items():
        if field not in enabled:
            continue
        if (new_value == "" or new_value is None) and not options.overwrite_empty:
            continue
        old_value = current.get(field, "")
        if str(old_value or "") != str(new_value or ""):
            changes.append(TagChange(field, old_value, new_value))
    if options.write_style_to_genre and wanted["dance_style"]:
        old = current.get("genre", "")
        if old != wanted["dance_style"]:
            changes.append(TagChange("genre", old, wanted["dance_style"]))
    return changes

