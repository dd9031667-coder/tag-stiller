from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.updater import (
    ARCHIVE_NAME, CHECKSUM_NAME, PreparedUpdate, is_newer_version,
    launch_prepared_update, parse_release, version_tuple,
)


def test_versions_are_compared_numerically():
    assert version_tuple("v1.2") == (1, 2, 0)
    assert is_newer_version("1.10.0", "1.9.9")
    assert not is_newer_version("1.1.0", "1.1.0")


def test_release_assets_are_selected_by_exact_name():
    release = parse_release({
        "tag_name": "v1.2.3",
        "name": "TagStiller 1.2.3",
        "html_url": "https://example.test/release",
        "assets": [
            {
                "name": ARCHIVE_NAME,
                "browser_download_url": "https://example.test/app.zip",
            },
            {
                "name": CHECKSUM_NAME,
                "browser_download_url": "https://example.test/app.sha256",
            },
        ],
    })
    assert release.version == "1.2.3"
    assert release.archive_url.endswith("app.zip")
    assert release.checksum_url.endswith("app.sha256")


def test_release_requires_archive_and_checksum():
    with pytest.raises(RuntimeError, match="контрольной суммы"):
        parse_release({
            "tag_name": "v1.2.3",
            "assets": [{
                "name": ARCHIVE_NAME,
                "browser_download_url": "https://example.test/app.zip",
            }],
        })


def test_updater_process_starts_outside_application_folder(tmp_path):
    application = tmp_path / "TagStiller"
    application.mkdir()
    script = tmp_path / "scripts" / "update.ps1"
    script.parent.mkdir()
    script.write_text("", encoding="utf-8")
    update = PreparedUpdate(
        version="2.0.0",
        source_dir=tmp_path / "new",
        target_dir=application,
        executable_name="TagStiller.exe",
        script_path=script,
    )
    with patch("app.services.updater.subprocess.Popen") as popen:
        launch_prepared_update(update)
    assert Path(popen.call_args.kwargs["cwd"]) == script.parent
    assert Path(popen.call_args.kwargs["cwd"]) != application
