from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


REPOSITORY = "dd9031667-coder/tag-stiller"
RELEASE_API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ARCHIVE_NAME = "TagStiller-Windows-x64.zip"
CHECKSUM_NAME = f"{ARCHIVE_NAME}.sha256"


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag_name: str
    release_name: str
    page_url: str
    archive_url: str
    checksum_url: str


@dataclass(frozen=True)
class PreparedUpdate:
    version: str
    source_dir: Path
    target_dir: Path
    executable_name: str
    script_path: Path


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.fullmatch(r"\s*v?(\d+(?:\.\d+)*)\s*", value)
    if not match:
        raise ValueError(f"Некорректная версия: {value}")
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts + (0,) * max(0, 3 - len(parts))


def is_newer_version(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def parse_release(payload: dict) -> ReleaseInfo:
    tag_name = str(payload.get("tag_name", "")).strip()
    version_tuple(tag_name)
    assets = {
        str(asset.get("name", "")): str(asset.get("browser_download_url", ""))
        for asset in payload.get("assets", [])
        if isinstance(asset, dict)
    }
    archive_url = assets.get(ARCHIVE_NAME, "")
    checksum_url = assets.get(CHECKSUM_NAME, "")
    if not archive_url or not checksum_url:
        raise RuntimeError(
            "В последнем релизе отсутствует ZIP приложения или файл контрольной суммы."
        )
    return ReleaseInfo(
        version=tag_name.removeprefix("v"),
        tag_name=tag_name,
        release_name=str(payload.get("name") or tag_name),
        page_url=str(payload.get("html_url", "")),
        archive_url=archive_url,
        checksum_url=checksum_url,
    )


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "TagStiller-Updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _read_url(url: str, timeout: int = 30) -> bytes:
    with urllib.request.urlopen(_request(url), timeout=timeout) as response:
        return response.read()


def fetch_latest_release() -> ReleaseInfo:
    try:
        payload = json.loads(_read_url(RELEASE_API_URL).decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Не удалось получить данные о последнем релизе: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub вернул некорректные данные релиза.")
    return parse_release(payload)


def can_install_automatically() -> bool:
    return (
        sys.platform == "win32"
        and bool(getattr(sys, "frozen", False))
        and Path(sys.executable).name.casefold() == "tagstiller.exe"
    )


def _download(url: str, destination: Path, timeout: int = 120) -> None:
    with urllib.request.urlopen(_request(url), timeout=timeout) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def _expected_checksum(raw: bytes) -> str:
    match = re.search(rb"\b([0-9a-fA-F]{64})\b", raw)
    if not match:
        raise RuntimeError("Файл контрольной суммы имеет некорректный формат.")
    return match.group(1).decode("ascii").lower()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if target != destination_resolved and destination_resolved not in target.parents:
                raise RuntimeError("ZIP обновления содержит небезопасный путь.")
        bundle.extractall(destination)


def _powershell_script() -> str:
    return r"""param(
    [Parameter(Mandatory=$true)][int]$ProcessId,
    [Parameter(Mandatory=$true)][string]$SourceDir,
    [Parameter(Mandatory=$true)][string]$TargetDir,
    [Parameter(Mandatory=$true)][string]$ExecutableName
)

$ErrorActionPreference = "Stop"
$backupDir = "$TargetDir.tagstiller-old-$ProcessId"

try {
    Wait-Process -Id $ProcessId -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $TargetDir -Destination $backupDir
    try {
        Move-Item -LiteralPath $SourceDir -Destination $TargetDir
    }
    catch {
        Move-Item -LiteralPath $backupDir -Destination $TargetDir
        throw
    }
    Start-Process -FilePath (Join-Path $TargetDir $ExecutableName)
    Start-Sleep -Seconds 3
    Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue
}
catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "Не удалось установить обновление:`n$($_.Exception.Message)",
        "TagStiller"
    )
}
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""


def prepare_update(
    release: ReleaseInfo,
    target_dir: Path | None = None,
    executable_name: str = "TagStiller.exe",
) -> PreparedUpdate:
    target = (target_dir or Path(sys.executable).parent).resolve()
    if not target.is_dir():
        raise RuntimeError(f"Папка приложения не найдена: {target}")

    archive_handle, archive_name = tempfile.mkstemp(
        prefix="tagstiller-", suffix=".zip"
    )
    os.close(archive_handle)
    archive = Path(archive_name)
    source = Path(
        tempfile.mkdtemp(prefix=".tagstiller-update-", dir=target.parent)
    ).resolve()
    script_handle, script_name = tempfile.mkstemp(
        prefix="tagstiller-update-", suffix=".ps1"
    )
    os.close(script_handle)
    script = Path(script_name)

    try:
        _download(release.archive_url, archive)
        expected = _expected_checksum(_read_url(release.checksum_url))
        actual = _file_sha256(archive)
        if actual != expected:
            raise RuntimeError(
                "Контрольная сумма обновления не совпала. Установка отменена."
            )
        _safe_extract(archive, source)
        if not (source / executable_name).is_file():
            raise RuntimeError(f"В обновлении не найден {executable_name}.")
        script.write_text(_powershell_script(), encoding="utf-8-sig")
    except Exception:
        shutil.rmtree(source, ignore_errors=True)
        script.unlink(missing_ok=True)
        raise
    finally:
        archive.unlink(missing_ok=True)

    return PreparedUpdate(
        version=release.version,
        source_dir=source,
        target_dir=target,
        executable_name=executable_name,
        script_path=script,
    )


def launch_prepared_update(update: PreparedUpdate) -> None:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(update.script_path),
        "-ProcessId",
        str(os.getpid()),
        "-SourceDir",
        str(update.source_dir),
        "-TargetDir",
        str(update.target_dir),
        "-ExecutableName",
        update.executable_name,
    ]
    subprocess.Popen(
        command,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def discard_prepared_update(update: PreparedUpdate) -> None:
    shutil.rmtree(update.source_dir, ignore_errors=True)
    update.script_path.unlink(missing_ok=True)
