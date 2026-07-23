from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher

from app.models import AlbumMetadata, LocalAudioFile, MatchStatus, TrackMatch
from app.utils.text import normalize_text


def _key(disc: int | None, track: int | None) -> tuple[int, int | None]:
    return (disc or 1, track)


def _name_score(local: LocalAudioFile, title: str) -> float:
    candidate = local.title or local.path.stem
    return SequenceMatcher(None, normalize_text(candidate), normalize_text(title)).ratio()


def match_tracks(
    album: AlbumMetadata,
    files: list[LocalAudioFile],
    duration_tolerance: float = 4.0,
) -> list[TrackMatch]:
    by_key: dict[tuple[int, int | None], list[LocalAudioFile]] = defaultdict(list)
    for local in files:
        by_key[_key(local.disc_number, local.track_number)].append(local)

    results: list[TrackMatch] = []
    for track in album.tracks:
        candidates = by_key[_key(track.disc_number, track.track_number)]
        if not candidates:
            results.append(TrackMatch(track, None, MatchStatus.RED, "Файл с этим номером не найден", enabled=False))
            continue
        if len(candidates) > 1:
            names = ", ".join(item.path.name for item in candidates)
            results.append(TrackMatch(track, None, MatchStatus.RED, f"Найдено несколько файлов: {names}", enabled=False))
            continue
        local = candidates[0]
        difference = None
        notes: list[str] = []
        status = MatchStatus.GREEN
        if local.duration_seconds is not None and track.duration_seconds is not None:
            difference = abs(local.duration_seconds - track.duration_seconds)
            if difference > duration_tolerance:
                status = MatchStatus.YELLOW
                notes.append(f"Длительность отличается на {difference:.1f} с")
        score = _name_score(local, track.title)
        if score < 0.35:
            status = MatchStatus.YELLOW
            notes.append("Название файла заметно отличается")
        elif score < 0.60 and not notes:
            notes.append("Совпадение подтверждено по номеру")
        results.append(TrackMatch(track, local, status, "; ".join(notes), difference))
    return results

