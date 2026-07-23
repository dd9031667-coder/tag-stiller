from __future__ import annotations

import os
import base64
import shutil
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TPUB, TRCK, TXXX, ID3,
    ID3NoHeaderError,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from app.audio.artwork import cover_from_value, cover_to_json


@dataclass(slots=True)
class TagOptions:
    track_number: bool = True
    disc_number: bool = True
    artist: bool = True
    title: bool = True
    album: bool = True
    album_artist: bool = True
    album_label: bool = True
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
    "language", "dance_style", "dance_tempo", "year", "album_label", "genre",
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
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
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
                "year": get("TDRC"), "album_label": get("TPUB"), "genre": get("TCON"),
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
                "year": atom("\xa9day"),
                "album_label": atom("----:com.apple.iTunes:LABEL"),
                "genre": atom("\xa9gen"),
            }
        def vorbis(key: str) -> str:
            return _scalar(tags.get(key) or tags.get(key.upper()))
        return {
            "track_number": vorbis("tracknumber"), "disc_number": vorbis("discnumber"),
            "artist": vorbis("artist"), "title": vorbis("title"), "album": vorbis("album"),
            "album_artist": vorbis("albumartist"), "language": vorbis("language"),
            "dance_style": vorbis("dance_style"), "dance_tempo": vorbis("dance_tempo"),
            "year": vorbis("date"), "album_label": vorbis("label"),
            "genre": vorbis("genre"),
        }

    def snapshot(self, path: str | Path) -> dict[str, Any]:
        """Снимок поддерживаемых тегов, включая обложку для JSON-backup."""
        values: dict[str, Any] = self.read_current(path)
        values["cover_art"] = cover_to_json(self.read_cover(path))
        return values

    def read_cover(self, path: str | Path) -> dict[str, Any] | None:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".mp3":
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                return None
            pictures = tags.getall("APIC")
            if not pictures:
                return None
            return {"mime": pictures[0].mime or "image/jpeg", "data": pictures[0].data}
        audio = MutagenFile(path)
        if audio is None:
            return None
        if isinstance(audio, MP4):
            covers = (audio.tags or {}).get("covr", [])
            if not covers:
                return None
            cover = covers[0]
            image_format = getattr(cover, "imageformat", None)
            mime = "image/png" if image_format == MP4Cover.FORMAT_PNG else "image/jpeg"
            return {"mime": mime, "data": bytes(cover)}
        if isinstance(audio, FLAC):
            if not audio.pictures:
                return None
            picture = audio.pictures[0]
            return {"mime": picture.mime or "image/jpeg", "data": picture.data}
        if isinstance(audio, (OggVorbis, OggOpus)):
            encoded = (audio.tags or {}).get("metadata_block_picture", [])
            if not encoded:
                return None
            picture = Picture(base64.b64decode(encoded[0]))
            return {"mime": picture.mime or "image/jpeg", "data": picture.data}
        return None

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
            "year": ("TDRC", TDRC), "album_label": ("TPUB", TPUB),
            "genre": ("TCON", TCON),
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
        if "cover_art" in values:
            tags.delall("APIC")
            cover = cover_from_value(values["cover_art"])
            if cover:
                mime, data = cover
                tags.add(APIC(
                    encoding=3, mime=mime, type=3, desc="Cover", data=data,
                ))
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
            "year": "DATE", "album_label": "LABEL", "genre": "GENRE",
        }
        for key, tag in keys.items():
            if key not in values:
                continue
            if values[key] in ("", None):
                audio.tags.pop(tag, None)
            else:
                audio.tags[tag] = [str(values[key])]
        if "cover_art" in values:
            cover = cover_from_value(values["cover_art"])
            if isinstance(audio, FLAC):
                audio.clear_pictures()
                if cover:
                    mime, data = cover
                    picture = Picture()
                    picture.type = 3
                    picture.mime = mime
                    picture.desc = "Cover"
                    picture.data = data
                    audio.add_picture(picture)
            else:
                audio.tags.pop("METADATA_BLOCK_PICTURE", None)
                if cover:
                    mime, data = cover
                    picture = Picture()
                    picture.type = 3
                    picture.mime = mime
                    picture.desc = "Cover"
                    picture.data = data
                    encoded = base64.b64encode(picture.write()).decode("ascii")
                    audio.tags["METADATA_BLOCK_PICTURE"] = [encoded]
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
        custom_atoms = {
            "language": "LANGUAGE",
            "dance_style": "DANCE_STYLE",
            "dance_tempo": "DANCE_TEMPO",
            "album_label": "LABEL",
        }
        for key, atom_name in custom_atoms.items():
            if key in values:
                atom = f"----:com.apple.iTunes:{atom_name}"
                if values[key] in ("", None):
                    audio.tags.pop(atom, None)
                else:
                    audio.tags[atom] = [str(values[key]).encode("utf-8")]
        if "cover_art" in values:
            audio.tags.pop("covr", None)
            cover = cover_from_value(values["cover_art"])
            if cover:
                mime, data = cover
                image_format = (
                    MP4Cover.FORMAT_PNG if mime == "image/png"
                    else MP4Cover.FORMAT_JPEG
                )
                audio.tags["covr"] = [MP4Cover(data, imageformat=image_format)]
        audio.save()
