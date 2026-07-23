from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import (
    TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, TXXX, ID3,
    ID3NoHeaderError,
)
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis


@dataclass(slots=True)
class TagOptions:
    track_number: bool = True
    disc_number: bool = True
    artist: bool = True
    title: bool = True
    album: bool = True
    album_artist: bool = True
    language: bool = True
    dance_style: bool = True
    dance_tempo: bool = True
    year: bool = True
    write_style_to_genre: bool = False
    overwrite_empty: bool = False

    def enabled_fields(self) -> set[str]:
        excluded = {"write_style_to_genre", "overwrite_empty"}
        return {item.name for item in fields(self) if item.name not in excluded and getattr(self, item.name)}


_CANONICAL = (
    "track_number", "disc_number", "artist", "title", "album", "album_artist",
    "language", "dance_style", "dance_tempo", "year", "genre",
)


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, tuple):
        value = value[0] if value else ""
    return str(value)


class TagService:
    """Чтение и атомарная запись поддерживаемых полей без изменения аудиопотока."""

    def read_current(self, path: str | Path) -> dict[str, str]:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".mp3":
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                return {key: "" for key in _CANONICAL}
            get = lambda key: _scalar(tags.get(key))
            custom = lambda desc: _scalar(tags.get(f"TXXX:{desc}"))
            return {
                "track_number": get("TRCK"), "disc_number": get("TPOS"),
                "artist": get("TPE1"), "title": get("TIT2"), "album": get("TALB"),
                "album_artist": get("TPE2"), "language": custom("LANGUAGE"),
                "dance_style": custom("DANCE_STYLE"), "dance_tempo": custom("DANCE_TEMPO"),
                "year": get("TDRC"), "genre": get("TCON"),
            }
        audio = MutagenFile(path)
        if audio is None:
            raise ValueError(f"Неподдерживаемый аудиофайл: {path.name}")
        tags = audio.tags or {}
        if isinstance(audio, MP4):
            def atom(name: str) -> str:
                return _scalar(tags.get(name))
            return {
                "track_number": _scalar(tags.get("trkn")), "disc_number": _scalar(tags.get("disk")),
                "artist": atom("\xa9ART"), "title": atom("\xa9nam"), "album": atom("\xa9alb"),
                "album_artist": atom("aART"),
                "language": atom("----:com.apple.iTunes:LANGUAGE"),
                "dance_style": atom("----:com.apple.iTunes:DANCE_STYLE"),
                "dance_tempo": atom("----:com.apple.iTunes:DANCE_TEMPO"),
                "year": atom("\xa9day"), "genre": atom("\xa9gen"),
            }
        def vorbis(key: str) -> str:
            return _scalar(tags.get(key) or tags.get(key.upper()))
        return {
            "track_number": vorbis("tracknumber"), "disc_number": vorbis("discnumber"),
            "artist": vorbis("artist"), "title": vorbis("title"), "album": vorbis("album"),
            "album_artist": vorbis("albumartist"), "language": vorbis("language"),
            "dance_style": vorbis("dance_style"), "dance_tempo": vorbis("dance_tempo"),
            "year": vorbis("date"), "genre": vorbis("genre"),
        }

    def write_atomic(
        self,
        path: str | Path,
        values: dict[str, Any],
        full_backup_dir: str | Path | None = None,
    ) -> None:
        original = Path(path)
        if full_backup_dir:
            backup_dir = Path(full_backup_dir)
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, backup_dir / original.name)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{original.stem}.tagstiller-", suffix=original.suffix,
            dir=original.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(original, temporary)
            self._write(temporary, values)
            os.replace(temporary, original)
        finally:
            temporary.unlink(missing_ok=True)

    def _write(self, path: Path, values: dict[str, Any]) -> None:
        suffix = path.suffix.lower()
        if suffix == ".mp3":
            self._write_mp3(path, values)
        elif suffix in {".m4a", ".mp4"}:
            self._write_mp4(path, values)
        elif suffix in {".flac", ".ogg", ".opus"}:
            self._write_vorbis(path, values)
        else:
            raise ValueError(f"Формат {suffix} не поддерживается.")

    @staticmethod
    def _write_mp3(path: Path, values: dict[str, Any]) -> None:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        frames = {
            "track_number": ("TRCK", TRCK), "disc_number": ("TPOS", TPOS),
            "artist": ("TPE1", TPE1), "title": ("TIT2", TIT2),
            "album": ("TALB", TALB), "album_artist": ("TPE2", TPE2),
            "year": ("TDRC", TDRC), "genre": ("TCON", TCON),
        }
        for key, (frame_id, cls) in frames.items():
            if key not in values:
                continue
            tags.delall(frame_id)
            if values[key] not in ("", None):
                tags.add(cls(encoding=3, text=[str(values[key])]))
        for key, description in (
            ("language", "LANGUAGE"), ("dance_style", "DANCE_STYLE"),
            ("dance_tempo", "DANCE_TEMPO"),
        ):
            if key not in values:
                continue
            tags.delall(f"TXXX:{description}")
            if values[key] not in ("", None):
                tags.add(TXXX(encoding=3, desc=description, text=[str(values[key])]))
        tags.save(path, v2_version=4)

    @staticmethod
    def _write_vorbis(path: Path, values: dict[str, Any]) -> None:
        audio = MutagenFile(path)
        if not isinstance(audio, (FLAC, OggVorbis, OggOpus)):
            raise ValueError("Файл не является FLAC/OGG/OPUS.")
        if audio.tags is None:
            audio.add_tags()
        keys = {
            "track_number": "TRACKNUMBER", "disc_number": "DISCNUMBER",
            "artist": "ARTIST", "title": "TITLE", "album": "ALBUM",
            "album_artist": "ALBUMARTIST", "language": "LANGUAGE",
            "dance_style": "DANCE_STYLE", "dance_tempo": "DANCE_TEMPO",
            "year": "DATE", "genre": "GENRE",
        }
        for key, tag in keys.items():
            if key not in values:
                continue
            if values[key] in ("", None):
                audio.tags.pop(tag, None)
            else:
                audio.tags[tag] = [str(values[key])]
        audio.save()

    @staticmethod
    def _write_mp4(path: Path, values: dict[str, Any]) -> None:
        audio = MP4(path)
        if audio.tags is None:
            audio.add_tags()
        atoms = {
            "artist": "\xa9ART", "title": "\xa9nam", "album": "\xa9alb",
            "album_artist": "aART", "year": "\xa9day", "genre": "\xa9gen",
        }
        for key, atom in atoms.items():
            if key in values:
                if values[key] in ("", None):
                    audio.tags.pop(atom, None)
                else:
                    audio.tags[atom] = [str(values[key])]
        for key, atom in (("track_number", "trkn"), ("disc_number", "disk")):
            if key in values:
                if values[key] in ("", None):
                    audio.tags.pop(atom, None)
                else:
                    audio.tags[atom] = [(int(values[key]), 0)]
        for key in ("language", "dance_style", "dance_tempo"):
            if key in values:
                atom = f"----:com.apple.iTunes:{key.upper()}"
                if values[key] in ("", None):
                    audio.tags.pop(atom, None)
                else:
                    audio.tags[atom] = [str(values[key]).encode("utf-8")]
        audio.save()

