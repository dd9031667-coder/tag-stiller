from __future__ import annotations

import re
import unicodedata


_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})


def normalize_text(value: str | None) -> str:
    """Нормализация для сравнения, включая диакритику и пунктуацию."""
    text = unicodedata.normalize("NFKD", value or "")
    text = text.translate(_APOSTROPHES).translate(_DASHES)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"['\-]+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def parse_duration(value: str | None) -> float | None:
    if not value:
        return None
    match = re.fullmatch(r"\s*(?:(\d+):)?(\d+):(\d+)\s*", value)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
    match = re.fullmatch(r"\s*(\d+):(\d+)\s*", value)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    return None

