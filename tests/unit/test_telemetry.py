import io
import json
import logging

import pytest
import structlog

from app.telemetry import (
    NOISY_LOGGERS,
    REDACTED,
    bind,
    clear,
    configure_logging,
    get_logger,
    redact,
)


@pytest.fixture(autouse=True)
def reset_logging():  # type: ignore[no-untyped-def]
    yield
    clear()
    structlog.reset_defaults()
    logging.getLogger().handlers = []


def json_stream() -> io.StringIO:
    stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=stream)
    return stream


def lines(stream: io.StringIO) -> list[dict]:  # type: ignore[type-arg]
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_redact_masks_contact_data() -> None:
    event = redact(
        None,
        "info",
        {
            "event": "lead stored",
            "email": "contact@example.com",
            "phone": "+358401234567",
            "company": "Example Oy",
            "count": 3,
        },
    )

    assert event["email"] == REDACTED
    assert event["phone"] == REDACTED
    assert event["company"] == "Example Oy"
    assert event["count"] == 3


def test_redact_leaves_missing_values_alone() -> None:
    assert redact(None, "info", {"email": None})["email"] is None


def test_redaction_applies_to_emitted_logs() -> None:
    stream = json_stream()
    get_logger("test").info("lead stored", email="contact@example.com", city="Helsinki")

    entry = lines(stream)[0]
    assert entry["email"] == REDACTED
    assert entry["city"] == "Helsinki"


def test_json_format_is_machine_readable() -> None:
    stream = json_stream()
    get_logger("test").info("collection completed", collected=20, new_leads=15)

    entry = lines(stream)[0]
    assert entry["event"] == "collection completed"
    assert entry["level"] == "info"
    assert entry["collected"] == 20
    assert entry["new_leads"] == 15
    assert "timestamp" in entry


def test_bound_context_appears_on_every_event() -> None:
    stream = json_stream()
    bind(job=42, source="example_csv")

    logger = get_logger("test")
    logger.info("collection started")
    logger.info("collection completed", collected=20)

    entries = lines(stream)
    assert len(entries) == 2
    assert all(entry["job"] == 42 for entry in entries)
    assert all(entry["source"] == "example_csv" for entry in entries)


def test_clearing_context_stops_the_binding() -> None:
    stream = json_stream()
    bind(job=42)
    get_logger("test").info("first")
    clear()
    get_logger("test").info("second")

    entries = lines(stream)
    assert entries[0]["job"] == 42
    assert "job" not in entries[1]


def test_stdlib_logs_are_formatted_too() -> None:
    stream = json_stream()
    logging.getLogger("legacy.module").warning("something old")

    entry = lines(stream)[0]
    assert entry["event"] == "something old"
    assert entry["level"] == "warning"


def test_console_format_is_human_readable() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", log_format="console", stream=stream)
    bind(job=7)
    get_logger("test").info("collection started", source="example_csv")

    output = stream.getvalue()
    assert "collection started" in output
    assert "job=7" in output
    assert "source=example_csv" in output


def test_noisy_third_party_loggers_are_quieted() -> None:
    json_stream()
    for name in NOISY_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_level_is_respected() -> None:
    stream = io.StringIO()
    configure_logging(level="WARNING", log_format="json", stream=stream)

    get_logger("test").info("ignored")
    get_logger("test").warning("kept")

    entries = lines(stream)
    assert [entry["event"] for entry in entries] == ["kept"]
