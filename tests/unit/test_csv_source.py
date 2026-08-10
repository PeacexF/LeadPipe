from pathlib import Path

import pytest

from app.config.models import SourceConfig
from app.domain.models import RawRecord
from app.sources import RecordError, SourceError, build_source

MAPPING = {"company_name": "name", "email": "email", "city": "city"}


def make_source(path: Path, **extra: object) -> SourceConfig:
    return SourceConfig.model_validate(
        {"name": "test_csv", "type": "csv", "path": str(path), "mapping": MAPPING, **extra}
    )


async def collect(source) -> list:  # type: ignore[no-untyped-def, type-arg]
    try:
        return [item async for item in source.collect()]
    finally:
        await source.aclose()


def write_csv(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "data.csv"
    path.write_text(body)
    return path


async def test_reads_and_maps_columns(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "name,email,city\nExample Oy,contact@example.com,Helsinki\n")
    items = await collect(build_source(make_source(path)))

    assert len(items) == 1
    record = items[0]
    assert isinstance(record, RawRecord)
    assert record.fields == {
        "company_name": "Example Oy",
        "email": "contact@example.com",
        "city": "Helsinki",
    }
    assert record.raw["name"] == "Example Oy"
    assert record.source.name == "test_csv"


async def test_blank_values_become_none(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "name,email,city\nExample Oy,,   \n")
    record = (await collect(build_source(make_source(path))))[0]
    assert isinstance(record, RawRecord)
    assert record.fields["email"] is None
    assert record.fields["city"] is None


async def test_external_id_is_carried(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "id,name,email,city\nA-1,Example,a@example.com,Helsinki\n")
    record = (await collect(build_source(make_source(path, external_id_field="id"))))[0]
    assert isinstance(record, RawRecord)
    assert record.fields["external_id"] == "A-1"


async def test_bad_row_is_reported_without_ending_collection(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path,
        "name,email,city\n"
        "Good Oy,good@example.com,Helsinki\n"
        "Broken Oy,broken@example.com,Helsinki,extra,columns\n"
        "Also Good Oy,also@example.com,Turku\n",
    )
    items = await collect(build_source(make_source(path)))

    assert len(items) == 3
    assert isinstance(items[1], RecordError)
    assert [i for i in items if isinstance(i, RawRecord)] != []
    assert sum(isinstance(i, RawRecord) for i in items) == 2


async def test_missing_columns_fail_the_source(tmp_path: Path) -> None:
    path = write_csv(tmp_path, "name,city\nExample Oy,Helsinki\n")
    with pytest.raises(SourceError, match="columns not in file: email"):
        await collect(build_source(make_source(path)))


async def test_missing_file_fails_the_source(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="file not found"):
        await collect(build_source(make_source(tmp_path / "nope.csv")))


async def test_unknown_source_type_is_rejected() -> None:
    config = SourceConfig.model_validate({"name": "x", "type": "carrier-pigeon"})
    with pytest.raises(SourceError, match="unknown source type"):
        build_source(config)


async def test_shipped_example_dataset_parses() -> None:
    config = SourceConfig.model_validate(
        {
            "name": "example_csv",
            "type": "csv",
            "path": "examples/data/companies.csv",
            "external_id_field": "id",
            "mapping": {"company_name": "name", "email": "email", "city": "city"},
        }
    )
    items = await collect(build_source(config))
    assert len(items) == 20
    assert all(isinstance(item, RawRecord) for item in items)
