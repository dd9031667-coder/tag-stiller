from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from app.models import AlbumMetadata, TrackMetadata
from app.providers.base import CasaMusicaProvider, ProviderError
from app.utils.text import parse_duration, split_title_dance_suffix


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _metadata_value(soup: BeautifulSoup, text: str, labels: tuple[str, ...]) -> str:
    normalized_labels = {label.casefold().rstrip(":") for label in labels}
    for node in soup.find_all(string=True):
        node_text = _clean(str(node)).casefold().rstrip(":")
        if node_text not in normalized_labels:
            continue
        parent = node.parent
        if parent is None:
            continue
        if parent.name == "dt":
            sibling = parent.find_next_sibling("dd")
            if sibling:
                value = _clean(sibling.get_text(" ", strip=True))
                if value:
                    return value
        row = parent.find_parent("tr")
        if row:
            cells = row.find_all(["th", "td"])
            for index, cell in enumerate(cells[:-1]):
                if _clean(cell.get_text(" ", strip=True)).casefold().rstrip(":") in normalized_labels:
                    value = _clean(cells[index + 1].get_text(" ", strip=True))
                    if value:
                        return value
        container = parent.parent
        if container:
            parts = [_clean(part) for part in container.stripped_strings]
            for index, part in enumerate(parts[:-1]):
                if part.casefold().rstrip(":") in normalized_labels and parts[index + 1]:
                    return parts[index + 1]
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
        title = self._album_title(soup)
        page_text = soup.get_text("\n", strip=True)
        album_label = _metadata_value(
            soup, page_text, ("Album Label", "Record Label", "Album-Label"),
        )
        album_artist = _metadata_value(
            soup, page_text, ("Album Artist", "Album interpret"),
        )
        year = _metadata_value(soup, page_text, ("Album Year", "Release Year"))
        year_match = re.search(r"\b(?:19|20)\d{2}\b", year)
        year = year_match.group(0) if year_match else year

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
                album_label=album_label,
            ))
        if not tracks:
            raise ProviderError("Таблица найдена, но строки треков распознать не удалось.")
        return AlbumMetadata(
            title=title,
            tracks=tracks,
            album_artist=album_artist,
            year=year,
            source_url=source_url,
            album_label=album_label,
        )

    @staticmethod
    def _album_title(soup: BeautifulSoup) -> str:
        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, dict):
                    continue
                graph = item.get("@graph", [])
                candidates = [item, *(graph if isinstance(graph, list) else [])]
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    kind = candidate.get("@type", "")
                    kinds = kind if isinstance(kind, list) else [kind]
                    if any(value in {"Product", "MusicAlbum"} for value in kinds):
                        name = _clean(str(candidate.get("name", "")))
                        if name:
                            return name

        selectors = (
            "h1[itemprop='name']",
            "h1.product_name",
            "h1.product-title",
            ".product-detail-name h1",
            "main h1",
            "h1",
        )
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                title = _clean(node.get_text(" ", strip=True))
                if title:
                    return title

        meta = soup.select_one("meta[property='og:title'], meta[name='og:title']")
        if meta and meta.get("content"):
            return CasaMusicaHtmlParser._clean_document_title(str(meta["content"]))
        if soup.title:
            return CasaMusicaHtmlParser._clean_document_title(
                soup.title.get_text(" ", strip=True),
            )
        return ""

    @staticmethod
    def _clean_document_title(value: str) -> str:
        title = _clean(value)
        title = re.sub(r"(?i)^\s*casa\s+musica\s*[-–—|:]\s*", "", title)
        title = re.sub(r"(?i)\s*[-–—|:]\s*casa\s+musica\s*$", "", title)
        return title.strip()

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
