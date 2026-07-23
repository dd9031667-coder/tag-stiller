from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.audio.scanner import scan_folder
from app.matching import match_tracks
from app.providers.html_parser import CasaMusicaHtmlParser
from app.services.album_io import load_album_json, save_album_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка логики TagStiller без GUI")
    sub = parser.add_subparsers(dest="command", required=True)
    parse_cmd = sub.add_parser("parse-html", help="Распознать сохранённую страницу")
    parse_cmd.add_argument("html")
    parse_cmd.add_argument("-o", "--output", required=True)
    match_cmd = sub.add_parser("match", help="Сопоставить JSON альбома с папкой")
    match_cmd.add_argument("json")
    match_cmd.add_argument("folder")
    match_cmd.add_argument("--tolerance", type=float, default=4.0)
    args = parser.parse_args()
    if args.command == "parse-html":
        album = CasaMusicaHtmlParser().fetch_album(args.html)
        save_album_json(album, args.output)
        print(f"Сохранено треков: {len(album.tracks)}")
        return 0
    album = load_album_json(args.json)
    matches = match_tracks(album, scan_folder(args.folder), args.tolerance)
    print(json.dumps([
        {
            "track": item.track.track_number,
            "file": str(item.local_file.path) if item.local_file else None,
            "status": item.status.value,
            "note": item.note,
        }
        for item in matches
    ], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

