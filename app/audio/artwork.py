from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


SUPPORTED_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def find_cover_image(folder: str | Path) -> Path | None:
    root = Path(folder)
    candidates = sorted(
        (
            path for path in root.iterdir()
            if path.is_file()
            and path.stem.casefold() == "cover"
            and path.suffix.casefold() in SUPPORTED_COVER_EXTENSIONS
        ),
        key=lambda path: path.name.casefold(),
    )
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise ValueError(f"Найдено несколько файлов обложки: {names}")
    return candidates[0] if candidates else None


def load_cover_image(path: str | Path) -> dict[str, Any]:
    image_path = Path(path)
    data = image_path.read_bytes()
    if data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    else:
        raise ValueError("Обложка должна быть корректным JPEG или PNG-файлом.")
    return {"mime": mime, "data": data}


def cover_to_json(cover: dict[str, Any] | None) -> dict[str, str] | None:
    if not cover:
        return None
    return {
        "mime": str(cover["mime"]),
        "data_base64": base64.b64encode(bytes(cover["data"])).decode("ascii"),
    }


def cover_from_value(cover: dict[str, Any] | None) -> tuple[str, bytes] | None:
    if not cover:
        return None
    if "data" in cover:
        return str(cover["mime"]), bytes(cover["data"])
    if "data_base64" in cover:
        return str(cover["mime"]), base64.b64decode(cover["data_base64"])
    raise ValueError("Некорректные данные обложки в backup.")
