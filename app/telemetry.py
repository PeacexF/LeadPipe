import logging
from collections.abc import MutableMapping
from typing import Any, TextIO

import structlog

# collected contact data must never reach the logs
SENSITIVE_KEYS = frozenset(
    {
        "address",
        "api_key",
        "authorization",
        "contact_name",
        "email",
        "password",
        "phone",
        "secret",
        "token",
        "website",
        "x-api-key",
    }
)

# third-party loggers that narrate every request or tick
NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "apscheduler",
    "asyncio",
    "aiosqlite",
    "urllib3",
)

REDACTED = "[redacted]"


def redact(
    logger: Any, name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in SENSITIVE_KEYS and event_dict[key] is not None:
            event_dict[key] = REDACTED
    return event_dict


def configure_logging(
    level: str = "INFO",
    log_format: str = "console",
    stream: TextIO | None = None,
) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact,
    ]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if log_format.lower() == "json"
        else structlog.dev.ConsoleRenderer(colors=stream is None)
    )
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def bind(**values: Any) -> None:
    structlog.contextvars.bind_contextvars(**values)


def unbind(*keys: str) -> None:
    structlog.contextvars.unbind_contextvars(*keys)


def clear() -> None:
    structlog.contextvars.clear_contextvars()
