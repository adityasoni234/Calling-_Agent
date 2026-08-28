#!/usr/bin/env bash
# Wait for Postgres, apply migrations, then hand off to the CMD.
set -euo pipefail

echo "[entrypoint] waiting for the database..."
for attempt in $(seq 1 60); do
    if python -c "
import asyncio, sys
from sqlalchemy import text
from app.db.session import engine

async def check():
    async with engine.connect() as conn:
        await conn.execute(text('SELECT 1'))

try:
    asyncio.run(check())
except Exception as exc:
    print(exc, file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; then
        echo "[entrypoint] database is up (attempt ${attempt})"
        break
    fi
    if [ "${attempt}" -eq 60 ]; then
        echo "[entrypoint] database did not become available in time" >&2
        exit 1
    fi
    sleep 1
done

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] applying migrations..."
    alembic upgrade head
fi

echo "[entrypoint] starting: $*"
exec "$@"
