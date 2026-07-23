from __future__ import annotations

import logging
from pathlib import Path


def setup_logging() -> Path:
    log_dir = Path.home() / ".tagstiller"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "tagstiller.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    return log_path

