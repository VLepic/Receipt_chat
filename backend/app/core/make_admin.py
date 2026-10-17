"""Grant administrator access to an existing account from the container console."""

import argparse
import asyncio

from sqlalchemy import func, select

from app.core.db import async_session_maker, engine
from app.models.user import User


async def promote(email: str) -> None:
    try:
        async with async_session_maker() as session:
            user = await session.scalar(select(User).where(func.lower(User.email) == email.lower()))
            if user is None:
                raise SystemExit("Account not found. Register the account first.")
            user.is_superuser = True
            await session.commit()
            print("Administrator access granted.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    asyncio.run(promote(parser.parse_args().email))
