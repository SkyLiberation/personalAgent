from __future__ import annotations

import json
import logging
import logging.config
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from uuid import uuid4


def setup_logging(log_level: str = "INFO") -> Path:
    project_root = Path(__file__).resolve().parents[3]
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


def log_event(logger: logging.Logger, level: int, event: str, **fields: object) -> None:
    logger.log(level, "%s | %s", event, _serialize_fields(fields))


@contextmanager
def trace_span(logger: logging.Logger, span_name: str, trace_id: str | None = None, **fields: object):
    trace = trace_id or uuid4().hex[:12]
    start = perf_counter()
    log_event(logger, logging.INFO, "trace.start", trace_id=trace, span=span_name, **fields)
    try:
        yield {"trace_id": trace, "span": span_name}
    except Exception as exc:
        duration_ms = round((perf_counter() - start) * 1000, 2)
        log_event(
            logger,
            logging.ERROR,
            "trace.error",
            trace_id=trace,
            span=span_name,
            duration_ms=duration_ms,
            error_type=exc.__class__.__name__,
            error=str(exc)[:500],
            **fields,
        )
        raise
    else:
        duration_ms = round((perf_counter() - start) * 1000, 2)
        log_event(
            logger,
            logging.INFO,
            "trace.end",
            trace_id=trace,
            span=span_name,
            duration_ms=duration_ms,
            **fields,
        )


def _serialize_fields(fields: dict[str, object]) -> str:
    compact = {key: value for key, value in fields.items() if value is not None}
    return json.dumps(compact, ensure_ascii=False, sort_keys=True, default=str)
