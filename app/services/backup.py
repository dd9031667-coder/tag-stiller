from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.audio.tags import TagService
from app.models import BackupRecord


class BackupService:
    def __init__(self, tag_service: TagService | None = None):
        self.tags = tag_service or TagService()

    def create(self, audio_paths: list[str | Path], destination: str | Path) -> list[BackupRecord]:
        records = [
            BackupRecord(
                path=str(Path(path).resolve()),
                format=Path(path).suffix.lower().lstrip("."),
                tags=(
                    self.tags.snapshot(path)
                    if hasattr(self.tags, "snapshot")
                    else self.tags.read_current(path)
                ),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            for path in audio_paths
        ]
        payload = {"version": 1, "records": [asdict(item) for item in records]}
        Path(destination).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        return records

    @staticmethod
    def load(path: str | Path) -> list[BackupRecord]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            raise ValueError("Неподдерживаемая версия backup JSON.")
        return [BackupRecord(**item) for item in payload.get("records", [])]

    def restore(self, backup_path: str | Path) -> tuple[list[str], list[str]]:
        restored: list[str] = []
        errors: list[str] = []
        for record in self.load(backup_path):
            try:
                target = Path(record.path)
                if not target.is_file():
                    raise FileNotFoundError("файл не найден")
                self.tags.write_atomic(target, record.tags)
                restored.append(record.path)
            except Exception as exc:
                errors.append(f"{record.path}: {exc}")
        return restored, errors

    @staticmethod
    def remap_paths(backup_path: str | Path, mapping: dict[str, str]) -> None:
        """Обновить пути backup после успешного переименования файлов."""
        if not mapping:
            return
        path = Path(backup_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        normalized = {
            str(Path(old).resolve()): str(Path(new).resolve())
            for old, new in mapping.items()
        }
        for record in payload.get("records", []):
            old_path = str(Path(record["path"]).resolve())
            if old_path in normalized:
                record["path"] = normalized[old_path]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
