from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from app.models import AlbumMetadata, TrackMetadata
from app.providers.base import CasaMusicaProvider, ProviderError
from app.utils.text import parse_duration, split_title_dance_suffix


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _metadata_value(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*:?\s*([^\n\r]+)", text, re.I)
        if match:
            return _clean(match.group(1))
    return ""


class CasaMusicaHtmlParser(CasaMusicaProvider):
    def fetch_album(self, source: str) -> AlbumMetadata:
        path = Path(source).resolve()
        if not path.is_file():
            raise ProviderError("Локальный HTML-файл не найден.")
        return self.parse(path.read_text(encoding="utf-8", errors="replace"), path.as_uri())

    def parse(self, html: str, source_url: str = "") -> AlbumMetadata:
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one("h1, [itemprop='name'], .page-title")
        title = _clean(title_node.get_text(" ", strip=True)) if title_node else ""
        page_text = soup.get_text("\n", strip=True)
        album_artist = _metadata_value(page_text, ("Album Artist", "Album interpret"))
        year = _metadata_value(page_text, ("Album Year", "Release Year"))

        table, headers = self._find_track_table(soup)
        if table is None:
            raise ProviderError("На странице не удалось найти таблицу треков.")

        tracks: list[TrackMetadata] = []
        rows = table.select("tbody tr") or table.select("tr")[1:]
        for row in rows:
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells:
                continue
            values = [_clean(cell.get_text(" ", strip=True)) for cell in cells]
            number_text = self._cell(values, headers, ("#", "no", "track", "nr"))
            number_match = re.search(r"(?:(\d+)\s*[-.])?\s*(\d+)", number_text)
            if not number_match:
                continue
            disc = int(number_match.group(1)) if number_match.group(1) else None
            number = int(number_match.group(2))
            raw_title = self._cell(values, headers, ("title", "titel"))
            artist = self._cell(values, headers, ("artist", "interpret"))
            language = self._cell(values, headers, ("language", "sprache"))
            site_style = self._cell(values, headers, ("style", "dance", "stil", "tanz"))
            length = self._cell(values, headers, ("length", "duration", "dauer", "time"))
            track_title, dance_style, tempo = split_title_dance_suffix(raw_title)
            tracks.append(TrackMetadata(
                disc_number=disc,
                track_number=number,
                title=track_title,
                artist=artist,
                language=language,
                dance_style=dance_style or site_style,
                dance_tempo=tempo,
                duration_seconds=parse_duration(length),
                album=title,
                album_artist=album_artist,
                year=year,
                source_url=source_url,
            ))
        if not tracks:
            raise ProviderError("Таблица найдена, но строки треков распознать не удалось.")
        return AlbumMetadata(title, tracks, album_artist, year, source_url)

    @staticmethod
    def _find_track_table(soup: BeautifulSoup) -> tuple[Tag | None, dict[str, int]]:
        best: tuple[int, Tag | None, dict[str, int]] = (0, None, {})
        for table in soup.find_all("table"):
            header_cells = table.select("thead th") or table.select("tr th") or table.select("tr:first-child td")
            names = [_clean(cell.get_text(" ", strip=True)).casefold() for cell in header_cells]
            headers = {name: index for index, name in enumerate(names)}
            score = sum(any(token in name for name in names) for token in ("title", "artist", "length", "duration", "language"))
            if score > best[0]:
                best = (score, table, headers)
        return (best[1], best[2]) if best[0] >= 2 else (None, {})

    @staticmethod
    def _cell(values: list[str], headers: dict[str, int], aliases: tuple[str, ...]) -> str:
        for header, index in headers.items():
            if any(header == alias or alias in header for alias in aliases):
                return values[index] if index < len(values) else ""
        if aliases[0] in ("#", "no") and values:
            return values[0]
        return ""
