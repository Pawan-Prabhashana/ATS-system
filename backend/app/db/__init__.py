"""SQLAlchemy layer for the Postgres store backend (STORE_BACKEND=postgres).

Only imported when the Postgres backend is selected (or by the test suite,
which runs the SQL stores against in-memory SQLite). The JSON stores remain the
default and depend on none of this.
"""
