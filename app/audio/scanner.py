from __future__ import annotations

import re
from pathlib import Path

from mutagen import File as MutagenFile

from app.models import LocalAudioFile


SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus"}

_POSITION_PATTERNS = [
    re.compile(r"(?i)^\s*cd\s*(?P<disc>\d+)\s*[-_. ]+\s*(?P<track>\d{1,3})(?=\D|$)"),
    re.compile(r"^\s*(?P<disc>\d+)\s*[-_.]\s*(?P<track>\d{1,3})(?=\D|$)"),
    re.compile(r"(?i)^\s*track\s*(?P<track>\d{1,3})(?=\D|$)"),
    re.compile(r"^\s*(?P<track>\d{1,3})(?=\s*[-_. )]|\s|$)"),
]


def extract_track_position(filename: str) -> tuple[int | None, int | None]:
    stem = Path(filename).stem
    for pattern in _POSITION_PATTERNS:
        match = pattern.search(stem)
        if match:
            groups = match.groupdict()
            return (
                int(groups["disc"]) if groups.get("disc") else None,
                int(groups["track"]),
            )
    return None, None


def extract_title_hint(filename: str) -> str:
    """Название из имени файла без распознанного префикса диска/трека."""
    stem = Path(filename).stem.strip()
    patterns = [
        re.compile(r"(?i)^\s*cd\s*\d+\s*[-_. ]+\s*\d{1,3}\s*[-_. )]*\s*"),
        re.compile(r"^\s*\d+\s*[-_.]\s*\d{1,3}\s*[-_. )]*\s*"),
        re.compile(r"(?i)^\s*track\s*\d{1,3}\s*[-_. )]*\s*"),
        re.compile(r"^\s*\d{1,3}\s*[-_. )]+\s*"),
    ]
    for pattern in patterns:
        cleaned = pattern.sub("", stem, count=1).strip()
        if cleaned != stem:
            return cleaned.replace("_", " ").strip() or stem
    return stem.replace("_", " ").strip()


def _first(tags: object, keys: tuple[str, ...]) -> str:
    if not tags:
        return ""
    for key in keys:
        try:
            value = tags.get(key)  # type: ignore[attr-defined]
            if value:
                if hasattr(value, "text"):
                    value = value.text
                if isinstance(value, (list, tuple)):
                    value = value[0]
                return str(value)
        except (AttributeError, KeyError, TypeError):
            continue
    return ""


def inspect_audio(path: Path) -> LocalAudioFile:
    disc, track = extract_track_position(path.name)
    duration = None
    artist = title = ""
    try:
        audio = MutagenFile(path, easy=True)
        if audio is not None:
            duration = float(audio.info.length) if getattr(audio, "info", None) else None
            artist = _first(audio.tags, ("artist", "\xa9ART", "TPE1"))
            title = _first(audio.tags, ("title", "\xa9nam", "TIT2"))
            if track is None:
                raw = _first(audio.tags, ("tracknumber", "trkn", "TRCK"))
                found = re.match(r"(\d+)", raw)
                track = int(found.group(1)) if found else None
            if disc is None:
                raw = _first(audio.tags, ("discnumber", "disk", "TPOS"))
                found = re.match(r"(\d+)", raw)
                disc = int(found.group(1)) if found else None
    except Exception:
        pass
    return LocalAudioFile(path, disc, track, duration, artist, title)


def scan_folder(folder: str | Path, recursive: bool = False) -> list[LocalAudioFile]:
    root = Path(folder)
    if not root.is_dir():
        raise ValueError("Указанная папка не существует.")
    iterator = root.rglob("*") if recursive else root.iterdir()
    paths = sorted(
        (p for p in iterator if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda p: p.name.casefold(),
    )
    return [inspect_audio(path) for path in paths]
