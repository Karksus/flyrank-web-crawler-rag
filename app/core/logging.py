import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings

_configured = False


def configure_logging() -> None:
    """Configure application-wide logging (console + rotating file).

    Safe to call multiple times (e.g. under uvicorn --reload).
    """
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if settings.LOG_FILE:
        log_path = Path(settings.LOG_FILE)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(
                RotatingFileHandler(
                    log_path,
                    maxBytes=settings.LOG_MAX_BYTES,
                    backupCount=settings.LOG_BACKUP_COUNT,
                    encoding="utf-8",
                )
            )
        except OSError:
            # Never let logging setup take the app down.
            logging.getLogger(__name__).warning(
                "Could not open log file %s; logging to console only", settings.LOG_FILE
            )

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=handlers, force=True)

    # Keep third-party libraries quiet unless we are debugging.
    if level > logging.DEBUG:
        for noisy in ("httpx", "httpcore", "huggingface_hub", "urllib3", "sentence_transformers"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).debug("Logging configured (level=%s, file=%s)", settings.LOG_LEVEL, settings.LOG_FILE)
