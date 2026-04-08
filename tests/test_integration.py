"""
Integration tests — verify the database behaves correctly as a whole system.

These tests exercise:
  - CHECK constraint enforcement (negative prices, invalid statuses, etc.)
  - Foreign key enforcement (orphan inserts rejected)
  - UNIQUE constraint enforcement (duplicate emails, duplicate line items)
  - Analytical query patterns the NL-SQL agent will run
  - Reproducibility (deterministic seeding)
  - Full seed_db.main() file-based round-trip
"""

import sqlite3
import random
from pathlib import Path
import tempfile

import pytest

import seed_db


# ---------------------------------------------------------------------------
# Constraint enforcement — the database must reject bad data
# ---------------------------------------------------------------------------

class TestCheckConstraints:
    """Verify that CHECK constraints block invalid inserts."""

    def test_negative_price_rejected(self, empty_conn):
        empty_conn.execute("INSERT INTO categories VALUES (1, 'Test')")
        with pytest.raises(sqlite3.IntegrityError):
            empty_conn.execute(
                "INSERT INTO products VALUES (1, 'Bad', 1, -9.99, 50)"
            )

    def test_zero_quantity_rejected(self, seeded_db):
        with pytest.raises(sqlite3.IntegrityError):
            seeded_db.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                "VALUES (1, 1, 0, 10.00)"
            )

    def test_invalid_status_rejected(self, seeded_db):
        with pytest.raises(sqlite3.IntegrityError):
            seeded_db.execute(
                "INSERT INTO orders (customer_id, order_date, status, total) "
                "VALUES (1, '2024-06-01', 'invalid_status', 0.0)"
            )

    def test_negative_stock_rejected(self, empty_conn):
        empty_conn.execute("INSERT INTO categories VALUES (1, 'Test')")
        with pytest.raises(sqlite3.IntegrityError):
            empty_conn.execute(
                "INSERT INTO products VALUES (1, 'Bad', 1, 9.99, -5)"
            )

    def test_negative_total_rejected(self, seeded_db):
        with pytest.raises(sqlite3.IntegrityError):
            seeded_db.execute(
                "INSERT INTO orders (customer_id, order_date, status, total) "
                "VALUES (1, '2024-06-01', 'processing', -100.0)"
            )

    def test_state_length_check(self, empty_conn):
        """State must be exactly 2 characters."""
        with pytest.raises(sqlite3.IntegrityError):
            empty_conn.execute(
                "INSERT INTO customers VALUES (1, 'A', 'B', 'a@b.com', 'City', 'XYZ', '2024-01-01')"
            )


class TestForeignKeyEnforcement:
    """Verify FK constraints prevent orphan rows."""

    def test_order_with_invalid_customer_rejected(self, empty_conn):
        with pytest.raises(sqlite3.IntegrityError):
            empty_conn.execute(
                "INSERT INTO orders (customer_id, order_date, status, total) "
                "VALUES (9999, '2024-06-01', 'processing', 0.0)"
            )

    def test_product_with_invalid_category_rejected(self, empty_conn):
        with pytest.raises(sqlite3.IntegrityError):
            empty_conn.execute(
                "INSERT INTO products VALUES (1, 'Ghost', 9999, 10.0, 50)"
            )

    def test_order_item_with_invalid_order_rejected(self, seeded_db):
        with pytest.raises(sqlite3.IntegrityError):
            seeded_db.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                "VALUES (99999, 1, 1, 10.00)"
            )

    def test_order_item_with_invalid_product_rejected(self, seeded_db):
        with pytest.raises(sqlite3.IntegrityError):
            seeded_db.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                "VALUES (1, 99999, 1, 10.00)"
            )

    def test_delete_customer_with_orders_blocked(self, seeded_db):
        """NO ACTION FK should prevent deleting a customer who has orders."""
        cust_with_order = seeded_db.execute(
            "SELECT customer_id FROM orders LIMIT 1"
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            seeded_db.execute(
                "DELETE FROM customers WHERE customer_id = ?", (cust_with_order,)
            )


class TestUniqueConstraints:
    """Verify UNIQUE constraints prevent duplicate inserts."""

    def test_duplicate_email_rejected(self, empty_conn):
        empty_conn.execute(
            "INSERT INTO customers VALUES (1, 'A', 'B', 'dup@test.com', 'NYC', 'NY', '2024-01-01')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            empty_conn.execute(
                "INSERT INTO customers VALUES (2, 'C', 'D', 'dup@test.com', 'LA', 'CA', '2024-01-01')"
            )

    def test_duplicate_category_name_rejected(self, empty_conn):
        empty_conn.execute("INSERT INTO categories VALUES (1, 'Electronics')")
        with pytest.raises(sqlite3.IntegrityError):
            empty_conn.execute("INSERT INTO categories VALUES (2, 'Electronics')")

    def test_duplicate_product_per_order_rejected(self, seeded_db):
        """UNIQUE(order_id, product_id) must block duplicate line items."""
        # Find an existing order_item to duplicate
        row = seeded_db.execute(
            "SELECT order_id, product_id FROM order_items LIMIT 1"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            seeded_db.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                "VALUES (?, ?, 1, 10.00)",
                (row[0], row[1]),
            )


# ---------------------------------------------------------------------------
# Analytical query patterns — the queries the NL-SQL agent will generate
# ---------------------------------------------------------------------------

class TestAnalyticalQueries:
    """
    Verify the schema supports the types of queries the agent will generate.
    These double as smoke tests for the seeded data.
    """

    def test_revenue_by_category(self, seeded_db):
        rows = seeded_db.execute("""
            SELECT c.category_name, ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            JOIN categories c ON p.category_id = c.category_id
            GROUP BY c.category_name
            ORDER BY revenue DESC
        """).fetchall()
        assert len(rows) == len(seed_db.CATEGORIES)
        assert all(rev > 0 for _, rev in rows)

    def test_top_customers_by_spend(self, seeded_db):
        rows = seeded_db.execute("""
            SELECT c.first_name || ' ' || c.last_name AS name,
                   ROUND(SUM(o.total), 2) AS total_spend
            FROM customers c
            JOIN orders o ON c.customer_id = o.customer_id
            WHERE o.status = 'completed'
            GROUP BY c.customer_id
            ORDER BY total_spend DESC
            LIMIT 10
        """).fetchall()
        assert len(rows) == 10
        assert rows[0][1] >= rows[9][1]  # sorted descending

    def test_monthly_order_count(self, seeded_db):
        rows = seeded_db.execute("""
            SELECT strftime('%Y-%m', order_date) AS month, COUNT(*) AS order_count
            FROM orders
            GROUP BY month
            ORDER BY month
        """).fetchall()
        assert len(rows) > 12  # spans > 12 months
        assert all(cnt > 0 for _, cnt in rows)

    def test_orders_by_city(self, seeded_db):
        rows = seeded_db.execute("""
            SELECT c.city, COUNT(o.order_id) AS order_count
            FROM customers c
            JOIN orders o ON c.customer_id = o.customer_id
            GROUP BY c.city
            ORDER BY order_count DESC
        """).fetchall()
        assert len(rows) > 0
        assert all(cnt > 0 for _, cnt in rows)

    def test_average_order_value(self, seeded_db):
        avg = seeded_db.execute(
            "SELECT AVG(total) FROM orders WHERE status = 'completed'"
        ).fetchone()[0]
        assert avg > 0

    def test_low_stock_products(self, seeded_db):
        """The agent should be able to answer: 'which products have low stock?'"""
        rows = seeded_db.execute(
            "SELECT product_name, stock_qty FROM products WHERE stock_qty < 50 ORDER BY stock_qty"
        ).fetchall()
        # Some products may have low stock given randint(20,500)
        assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# Reproducibility — same seed = same data
# ---------------------------------------------------------------------------

class TestReproducibility:

    def test_deterministic_output(self):
        """Two seeded databases with seed(42) should produce identical data."""
        def build_db():
            conn = sqlite3.connect(":memory:")
            conn.execute("PRAGMA foreign_keys=ON")
            random.seed(42)
            seed_db.create_tables(conn)
            cids = seed_db.seed_customers(conn)
            pids = seed_db.seed_categories_and_products(conn)
            seed_db.seed_orders(conn, cids, pids)
            conn.commit()
            return conn

        conn1 = build_db()
        conn2 = build_db()

        for table in ["customers", "categories", "products", "orders", "order_items"]:
            rows1 = conn1.execute(f"SELECT * FROM {table}").fetchall()
            rows2 = conn2.execute(f"SELECT * FROM {table}").fetchall()
            assert rows1 == rows2, f"Non-deterministic data in {table}"

        conn1.close()
        conn2.close()


# ---------------------------------------------------------------------------
# Full round-trip — seed_db.main() writes to disk correctly
# ---------------------------------------------------------------------------

class TestMainRoundTrip:

    def test_main_creates_db_file(self, tmp_path, monkeypatch):
        """seed_db.main() should create a .db file with all 5 tables populated."""
        db_file = tmp_path / "data" / "ecommerce.db"
        monkeypatch.setattr(seed_db, "DB_PATH", db_file)

        seed_db.main()

        assert db_file.exists()
        conn = sqlite3.connect(str(db_file))
        for table in ["customers", "categories", "products", "orders", "order_items"]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count > 0, f"{table} is empty after main()"
        conn.close()

    def test_main_is_idempotent(self, tmp_path, monkeypatch):
        """Running main() twice should produce the same database (drops + recreates)."""
        db_file = tmp_path / "data" / "ecommerce.db"
        monkeypatch.setattr(seed_db, "DB_PATH", db_file)

        seed_db.main()
        size1 = db_file.stat().st_size

        seed_db.main()
        size2 = db_file.stat().st_size

        # File sizes should be identical — same data both times
        assert size1 == size2
