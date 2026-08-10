import asyncio
import logging
from pathlib import Path
from typing import Annotated

import typer

from app.config import ConfigError, load_config
from app.db.session import create_engine, create_session_factory
from app.domain.filters import LeadFilter
from app.exports import FORMATS, export_leads
from app.pipeline import RunStats, run_collection
from app.repositories import LeadRepository
from app.settings import get_settings
from app.sources import SourceError
from app.validation import ValidationStatus

app = typer.Typer(add_completion=False, help="LeadPipe collection and processing.")

DEFAULT_CONFIG = Path("examples/configs/csv.yaml")


@app.command()
def collect(
    config: Annotated[Path, typer.Option("--config", "-c", help="Source configuration file.")] = (
        DEFAULT_CONFIG
    ),
    source: Annotated[str | None, typer.Option("--source", "-s", help="Source name.")] = None,
) -> None:
    """Run a collection for one source, or every enabled source."""
    _configure_logging()
    try:
        app_config = load_config(config)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc

    names = [source] if source else [s.name for s in app_config.enabled_sources()]
    if not names:
        typer.echo("No enabled sources in configuration.")
        raise typer.Exit(1)

    try:
        results = asyncio.run(_collect_all(app_config, names))
    except (SourceError, KeyError) as exc:
        typer.secho(f"Collection failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    for name, stats in results:
        _print_stats(name, stats)


@app.command()
def export(
    export_format: Annotated[str, typer.Option("--format", "-f", help="csv or json.")] = "csv",
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Output file.")] = None,
    source: Annotated[str | None, typer.Option("--source")] = None,
    country: Annotated[str | None, typer.Option("--country")] = None,
    city: Annotated[str | None, typer.Option("--city")] = None,
    status: Annotated[str | None, typer.Option("--status", help="valid/invalid/unknown.")] = None,
) -> None:
    """Export leads to a file, or to stdout when --out is omitted."""
    if export_format not in FORMATS:
        raise typer.BadParameter(f"format must be one of: {', '.join(FORMATS)}")
    try:
        validation_status = ValidationStatus(status) if status else None
    except ValueError as exc:
        raise typer.BadParameter(f"unknown status: {status}") from exc

    filters = LeadFilter(
        source=source, country=country, city=city, validation_status=validation_status
    )
    written = asyncio.run(_export(export_format, filters, out))
    if out is not None:
        typer.echo(f"Wrote {written} leads to {out}")


@app.command()
def sources(
    config: Annotated[Path, typer.Option("--config", "-c")] = DEFAULT_CONFIG,
) -> None:
    """List configured sources."""
    try:
        app_config = load_config(config)
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc

    for source_config in app_config.sources:
        state = "enabled" if source_config.enabled else "disabled"
        typer.echo(
            f"{source_config.name:<24} {source_config.type:<8} "
            f"priority={source_config.priority:<4} {state}"
        )


async def _collect_all(app_config, names: list[str]) -> list[tuple[str, RunStats]]:  # type: ignore[no-untyped-def]
    engine = create_engine(get_settings().database_url)
    factory = create_session_factory(engine)
    results: list[tuple[str, RunStats]] = []
    try:
        for name in names:
            async with factory() as session:
                stats = await run_collection(session, app_config, name)
                await session.commit()
            results.append((name, stats))
    finally:
        await engine.dispose()
    return results


async def _export(export_format: str, filters: LeadFilter, out: Path | None) -> int:
    engine = create_engine(get_settings().database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            total = await LeadRepository(session).count(filters)
            handle = out.open("w", encoding="utf-8") if out else None
            try:
                async for chunk in export_leads(session, export_format, filters):
                    if handle is not None:
                        handle.write(chunk)
                    else:
                        typer.echo(chunk, nl=False)
            finally:
                if handle is not None:
                    handle.close()
            return total
    finally:
        await engine.dispose()


def _print_stats(name: str, stats: RunStats) -> None:
    typer.secho(f"\nSource: {name}", bold=True)
    for label, value in (
        ("Collected", stats.collected),
        ("Valid", stats.valid),
        ("Invalid", stats.invalid),
        ("Unknown", stats.unknown),
        ("Duplicates", stats.duplicates),
        ("New leads", stats.new_leads),
        ("Needs review", stats.needs_review),
        ("Errors", stats.errors),
    ):
        typer.echo(f"  {label:<14} {value:>6}")


def _configure_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(levelname)-5s %(message)s",
    )


if __name__ == "__main__":
    app()
