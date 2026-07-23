from __future__ import annotations

import re
import unicodedata


_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})
_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})
_DANCE_SUFFIX = re.compile(
    r"\s*\((?P<style>[^()]*?\D)\s+(?P<tempo>\d{1,3}(?:[.,]\d+)?)"
    r"\s*(?:BPM|TPM)?\)\s*$",
    re.IGNORECASE,
)


def normalize_text(value: str | None) -> str:
    """Нормализация для сравнения, включая диакритику и пунктуацию."""
    text = unicodedata.normalize("NFKD", value or "")
    text = text.translate(_APOSTROPHES).translate(_DASHES)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"['\-]+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def split_title_dance_suffix(value: str) -> tuple[str, str, str]:
    """Убрать финальный ``(Dance 29)`` из Title и вернуть танец/темп отдельно."""
    title = re.sub(r"\s+", " ", value).strip()
    match = _DANCE_SUFFIX.search(title)
    if not match:
        return title, "", ""
    clean_title = title[:match.start()].rstrip(" -–—")
    return (
        clean_title,
        match.group("style").strip(),
        match.group("tempo").replace(",", "."),
    )


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
