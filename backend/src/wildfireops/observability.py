import logging
from typing import TextIO

import structlog


def configure_observability(
    environment: str,
    *,
    output: TextIO | None = None,
) -> None:
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if environment.strip().lower() == "production":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=False))

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(file=output),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,
    )
