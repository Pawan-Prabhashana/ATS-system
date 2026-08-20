"""Schema bootstrap: ``python -m app.db.init``.

Runs ``metadata.create_all()`` against the configured ``DATABASE_URL`` — creates
any missing tables and is idempotent (safe to re-run). Requires
``STORE_BACKEND``/``DATABASE_URL`` to point at your Postgres.

NOTE: this is intentionally not Alembic. Versioned migrations are future work;
for now the schema is additive and ``create_all`` is enough.
"""
from __future__ import annotations

from app.db.engine import create_all, get_engine


def main() -> None:
    engine = get_engine()
    create_all(engine)
    # Do not print the URL (it carries the password); the host is enough signal.
    print(f"Schema ready on {engine.url.host or engine.url.database}.")


if __name__ == "__main__":
    main()
