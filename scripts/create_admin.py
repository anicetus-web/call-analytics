"""
One-off setup script to create the first admin user.

Usage (inside the api/worker container, or any environment with DATABASE_URL set):
    python -m scripts.create_admin <login> <password> <name>
"""
import asyncio
import sys

from database import AsyncSessionLocal, User, UserRole
from api.auth import hash_password


async def create_admin(login: str, password: str, name: str) -> None:
    async with AsyncSessionLocal() as db:
        user = User(
            name=name,
            login=login,
            password_hash=hash_password(password),
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
        print(f"Created admin user id={user.id} login={login!r}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python -m scripts.create_admin <login> <password> <name>")
        sys.exit(1)
    asyncio.run(create_admin(sys.argv[1], sys.argv[2], sys.argv[3]))
