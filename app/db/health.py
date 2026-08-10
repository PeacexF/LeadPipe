from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ALEMBIC_INI = Path("alembic.ini")
MIGRATIONS = Path("migrations")


@dataclass(frozen=True, slots=True)
class Readiness:
    database: bool
    migrations_current: bool
    applied_revision: str | None = None
    expected_revision: str | None = None
    detail: str | None = None

    @property
    def ready(self) -> bool:
        return self.database and self.migrations_current


@lru_cache(maxsize=1)
def head_revision() -> str | None:
    if not ALEMBIC_INI.is_file() or not MIGRATIONS.is_dir():
        return None
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS))
    return ScriptDirectory.from_config(config).get_current_head()


async def check_readiness(session: AsyncSession) -> Readiness:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        return Readiness(database=False, migrations_current=False, detail=_reason(exc))

    try:
        expected = head_revision()
    except Exception as exc:
        expected = None
        return Readiness(database=True, migrations_current=False, detail=_reason(exc))

    try:
        applied = await session.scalar(text("SELECT version_num FROM alembic_version"))
    except Exception as exc:
        return Readiness(
            database=True,
            migrations_current=False,
            expected_revision=expected,
            detail=_reason(exc),
        )

    if expected is None:
        return Readiness(
            database=True,
            migrations_current=False,
            applied_revision=applied,
            detail="migration scripts not found",
        )

    return Readiness(
        database=True,
        migrations_current=applied == expected,
        applied_revision=applied,
        expected_revision=expected,
    )


def _reason(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:200]
