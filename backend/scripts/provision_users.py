"""Provision the reviewer accounts + bring the schema up to date (Postgres).

Run once against the production database to:
  1. add the new candidate attribution/portfolio columns (additive, safe),
  2. create the ``users`` table if missing (create_all),
  3. create/replace the reviewer accounts with freshly generated passwords.

It prints each user's generated password ONCE — copy them out and distribute
securely; only the pbkdf2 hash is stored in the DB. Re-running generates NEW
passwords for the listed users (leaves everything else untouched).

    STORE_BACKEND=postgres DATABASE_URL=... \
        python -m scripts.provision_users
"""
from __future__ import annotations

import secrets

from sqlalchemy import text

from app.config import get_store_backend
from app.db.engine import create_all, get_engine
from app.users import upsert_user

# Full names as given; usernames are the lowercased first name (all unique here).
REVIEWERS = [
    ("mahima", "Mahima Passela"),
    ("abdul", "Abdul Ashraff"),
    ("nidarshi", "Nidarshi Sivapadam"),
    ("pawan", "Pawan Prabhashana"),
]

# Additive column adds (safe, idempotent) for the candidates table.
_ALTERS = [
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS portfolio_url VARCHAR",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS decided_by VARCHAR",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS assignment_sent_by VARCHAR",
]


def main() -> int:
    if get_store_backend() != "postgres":
        print("Refusing to run: STORE_BACKEND must be 'postgres' (and DATABASE_URL set).")
        return 1

    eng = get_engine()
    print("1) Adding new candidate columns (additive)...")
    with eng.begin() as cx:
        for stmt in _ALTERS:
            cx.execute(text(stmt))
    print("   done.")

    print("2) Ensuring schema (create_all — creates the users table if missing)...")
    create_all(eng)
    print("   done.")

    print("3) Provisioning reviewer accounts...\n")
    creds = []
    for username, full_name in REVIEWERS:
        password = secrets.token_urlsafe(9)
        upsert_user(username, full_name, password, active=True)
        creds.append((username, full_name, password))

    width = max(len(u) for u, _, _ in creds)
    print("=" * 60)
    print("REVIEWER LOGINS — distribute securely; shown only once")
    print("=" * 60)
    for username, full_name, password in creds:
        print(f"  {username:<{width}}  {password}   ({full_name})")
    print("=" * 60)
    print("Login URL: the Vercel app. Passwords are stored hashed (pbkdf2).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
