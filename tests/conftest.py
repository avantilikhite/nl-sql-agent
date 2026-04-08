"""
Shared fixtures for the nl-sql-agent test suite.

Key fixture: `seeded_db` — an in-memory SQLite database populated with
the same seed data as the production DB (random.seed(42)).  Every test
that needs realistic data should use this fixture.
"""

import sqlite3
import random

import pytest

# Import the seed functions under test
import sys
from pathlib import Path

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed_db


@pytest.fixture()
def empty_conn():
    """Return a fresh in-memory SQLite connection with FKs enabled and tables created."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    seed_db.create_tables(conn)
    yield conn
    conn.close()


@pytest.fixture()
def seeded_db():
    """
    Return an in-memory SQLite connection fully seeded with deterministic data.

    Uses random.seed(42) — identical to the production seed_db.py output.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    random.seed(42)
    seed_db.create_tables(conn)
    customer_ids = seed_db.seed_customers(conn)
    product_ids = seed_db.seed_categories_and_products(conn)
    seed_db.seed_orders(conn, customer_ids, product_ids)
    conn.commit()
    yield conn
    conn.close()
