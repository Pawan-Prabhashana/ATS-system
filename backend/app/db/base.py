"""Declarative base for the ORM models.

Kept in its own module so ``app.db.models`` and ``app.db.engine`` can both
import ``Base`` without an import cycle.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all Catalist ORM tables."""
