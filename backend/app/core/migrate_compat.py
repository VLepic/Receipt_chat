import asyncio
import subprocess

import asyncpg

from app.core.config import settings


def _asyncpg_url() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _table_exists(connection: asyncpg.Connection, table_name: str) -> bool:
    return bool(
        await connection.fetchval(
            """
            select exists (
                select 1
                from information_schema.tables
                where table_schema = 'public' and table_name = $1
            )
            """,
            table_name,
        )
    )


async def main() -> None:
    connection = await asyncpg.connect(_asyncpg_url())
    try:
        has_user_table = await _table_exists(connection, "user")
        has_alembic_version = await _table_exists(connection, "alembic_version")
    finally:
        await connection.close()

    if has_user_table and not has_alembic_version:
        subprocess.run(["alembic", "stamp", "0001_initial"], check=True)


if __name__ == "__main__":
    asyncio.run(main())
