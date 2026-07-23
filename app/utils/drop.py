from __future__ import annotations

from pathlib import Path


def classify_dropped_paths(
    paths: list[str | Path],
) -> tuple[Path | None, Path | None]:
    html_files: list[Path] = []
    folders: list[Path] = []
    unsupported: list[Path] = []
    for value in paths:
        path = Path(value)
        if path.is_dir():
            folders.append(path.resolve())
        elif path.is_file() and path.suffix.casefold() in {".html", ".htm"}:
            html_files.append(path.resolve())
        else:
            unsupported.append(path)
    if len(html_files) > 1:
        raise ValueError("Перетащите только один HTML-файл.")
    if len(folders) > 1:
        raise ValueError("Перетащите только одну папку с аудиофайлами.")
    if not html_files and not folders:
        names = ", ".join(path.name for path in unsupported)
        raise ValueError(
            f"Поддерживаются HTML-файл и папка с аудио. Не распознано: {names}"
        )
    return (
        html_files[0] if html_files else None,
        folders[0] if folders else None,
    )
