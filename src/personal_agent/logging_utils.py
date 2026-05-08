from __future__ import annotations

import logging
import logging.config
from pathlib import Path


def setup_logging(log_level: str = "INFO") -> Path:
    project_root = Path(__file__).resolve().parents[2]
    log_dir = project_root / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "run.log"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": log_level,
                    "formatter": "standard",
                },
                "file": {
                    "class": "logging.FileHandler",
                    "level": log_level,
                    "formatter": "standard",
                    "filename": str(log_file),
                    "encoding": "utf-8",
                },
            },
            "root": {
                "level": log_level,
                "handlers": ["console", "file"],
            },
            "loggers": {
                "uvicorn": {"level": log_level, "handlers": ["console", "file"], "propagate": False},
                "uvicorn.error": {
                    "level": log_level,
                    "handlers": ["console", "file"],
                    "propagate": False,
                },
                "uvicorn.access": {
                    "level": log_level,
                    "handlers": ["console", "file"],
                    "propagate": False,
                },
            },
        }
    )
    return log_file
