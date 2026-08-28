"""Create a starting organization and owner account.

Idempotent: running it twice does not create a second account.

    python -m scripts.seed --email you@example.com --password 'a-real-password' \
        --name 'Your Name' --org 'Your Company'
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.errors import ConflictError
from app.db.session import SessionLocal
from app.services.auth_service import AuthService


async def seed(email: str, password: str, full_name: str, organization: str) -> int:
    async with SessionLocal() as session:
        service = AuthService(session)
        if await service.get_user_by_email(email):
            print(f"User {email} already exists; nothing to do.")
            return 0
        try:
            user = await service.register(
                email=email,
                password=password,
                full_name=full_name,
                organization_name=organization,
            )
        except ConflictError as exc:
            print(f"Could not seed: {exc.message}", file=sys.stderr)
            return 1
        print(f"Created {user.email} (role={user.role.value}) in organization '{organization}'.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the first account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="Owner")
    parser.add_argument("--org", default="My Company")
    args = parser.parse_args()
    return asyncio.run(seed(args.email, args.password, args.name, args.org))


if __name__ == "__main__":
    raise SystemExit(main())
