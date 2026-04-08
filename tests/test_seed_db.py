"""
Unit tests for seed_db.py — test individual functions in isolation.

Covers:
  - Table creation (schema correctness, STRICT mode, indexes)
  - Customer seeding (count, uniqueness, data validity)
  - Category & product seeding (counts, FK integrity)
  - Order seeding (counts, status distribution, total accuracy)
  - CHECK constraint enforcement
  - Data pool consistency
"""

import sqlite3
import random
import re
from datetime import datetime

import pytest

import seed_db


# ---------------------------------------------------------------------------
# Data pool sanity checks
# ---------------------------------------------------------------------------

class TestDataPools:
    """Verify the hardcoded data pools are internally consistent."""

    def test_all_categories_have_products(self):
        """Every entry in CATEGORIES must have a matching key in PRODUCTS."""
        for cat in seed_db.CATEGORIES:
            assert cat in seed_db.PRODUCTS, f"Category '{cat}' missing from PRODUCTS dict"

    def test_products_dict_has_no_extra_categories(self):
        """PRODUCTS should not contain categories not listed in CATEGORIES."""
        extra = set(seed_db.PRODUCTS.keys()) - set(seed_db.CATEGORIES)
        assert extra == set(), f"Extra categories in PRODUCTS: {extra}"

    def test_all_product_prices_positive(self):
        """Every product must have a price > 0."""
        for cat, items in seed_db.PRODUCTS.items():
            for name, price in items:
                assert price > 0, f"'{name}' in '{cat}' has non-positive price: {price}"

    def test_order_statuses_not_empty(self):
        assert len(seed_db.ORDER_STATUSES) > 0

    def test_cities_have_two_char_states(self):
        """Every (city, state) tuple must have a 2-character state code."""
        for city, state in seed_db.CITIES:
            assert len(state) == 2, f"State '{state}' for city '{city}' is not 2 characters"


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

class TestCreateTables:
    """Verify the schema produced by create_tables()."""

    def test_all_five_tables_exist(self, empty_conn):
        tables = {
            row[0]
            for row in empty_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        expected = {"customers", "categories", "products", "orders", "order_items"}
        assert tables == expected

    def test_strict_mode_enabled(self, empty_conn):
        """STRICT tables reject type mismatches — inserting TEXT into INTEGER should fail."""
        with pytest.raises(sqlite3.IntegrityError):
            empty_conn.execute(
                "INSERT INTO categories (category_id, category_name) VALUES ('not_an_int', 'Test')"
            )

    def test_indexes_created(self, empty_conn):
        indexes = {
            row[0]
            for row in empty_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )
        }
        expected = {
            "idx_orders_customer",
            "idx_orders_date",
            "idx_orders_status",
            "idx_order_items_order",
            "idx_products_category",
        }
        assert indexes == expected

    def test_idempotent_create(self, empty_conn):
        """Running create_tables twice should not raise — it drops first."""
        seed_db.create_tables(empty_conn)  # second call
        count = empty_conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        assert count == 5


# ---------------------------------------------------------------------------
# Customer seeding
# ---------------------------------------------------------------------------

class TestSeedCustomers:

    def test_correct_count(self, empty_conn):
        ids = seed_db.seed_customers(empty_conn, n=50)
        assert len(ids) == 50
        count = empty_conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        assert count == 50

    def test_default_count_200(self, empty_conn):
        random.seed(42)
        ids = seed_db.seed_customers(empty_conn)
        assert len(ids) == 200

    def test_emails_are_unique(self, empty_conn):
        random.seed(42)
        seed_db.seed_customers(empty_conn)
        emails = [
            row[0] for row in empty_conn.execute("SELECT email FROM customers")
        ]
        assert len(emails) == len(set(emails))

    def test_state_is_two_chars(self, empty_conn):
        random.seed(42)
        seed_db.seed_customers(empty_conn)
        states = [row[0] for row in empty_conn.execute("SELECT state FROM customers")]
        assert all(len(s) == 2 for s in states)

    def test_created_at_is_valid_iso_date(self, empty_conn):
        random.seed(42)
        seed_db.seed_customers(empty_conn)
        dates = [row[0] for row in empty_conn.execute("SELECT created_at FROM customers")]
        iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for d in dates:
            assert iso_re.match(d), f"Invalid date format: {d}"
            datetime.strptime(d, "%Y-%m-%d")  # also validates semantics

    def test_returns_list_of_ints(self, empty_conn):
        ids = seed_db.seed_customers(empty_conn, n=10)
        assert all(isinstance(i, int) for i in ids)


# ---------------------------------------------------------------------------
# Category & product seeding
# ---------------------------------------------------------------------------

class TestSeedCategoriesAndProducts:

    def test_category_count(self, empty_conn):
        random.seed(42)
        seed_db.seed_categories_and_products(empty_conn)
        count = empty_conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        assert count == len(seed_db.CATEGORIES)

    def test_product_count(self, empty_conn):
        random.seed(42)
        product_ids = seed_db.seed_categories_and_products(empty_conn)
        total_expected = sum(len(v) for v in seed_db.PRODUCTS.values())
        count = empty_conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        assert count == total_expected
        assert len(product_ids) == total_expected

    def test_every_product_has_valid_category_fk(self, empty_conn):
        random.seed(42)
        seed_db.seed_categories_and_products(empty_conn)
        orphans = empty_conn.execute("""
            SELECT p.product_id FROM products p
            LEFT JOIN categories c ON p.category_id = c.category_id
            WHERE c.category_id IS NULL
        """).fetchall()
        assert orphans == []

    def test_stock_qty_is_positive(self, empty_conn):
        random.seed(42)
        seed_db.seed_categories_and_products(empty_conn)
        min_stock = empty_conn.execute("SELECT MIN(stock_qty) FROM products").fetchone()[0]
        assert min_stock >= 20  # random.randint(20, 500)


# ---------------------------------------------------------------------------
# Order seeding
# ---------------------------------------------------------------------------

class TestSeedOrders:

    def test_order_count(self, seeded_db):
        count = seeded_db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        assert count == 1500

    def test_order_items_exist(self, seeded_db):
        """Every order should have at least one line item."""
        empty_orders = seeded_db.execute("""
            SELECT o.order_id FROM orders o
            LEFT JOIN order_items oi ON o.order_id = oi.order_id
            WHERE oi.item_id IS NULL
        """).fetchall()
        assert empty_orders == [], f"Orders with no items: {empty_orders}"

    def test_order_total_matches_line_items(self, seeded_db):
        """Denormalized total must equal SUM(quantity * unit_price) per order."""
        mismatches = seeded_db.execute("""
            SELECT o.order_id, o.total, ROUND(SUM(oi.quantity * oi.unit_price), 2) AS computed
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            GROUP BY o.order_id
            HAVING ABS(o.total - computed) > 0.01
        """).fetchall()
        assert mismatches == [], f"Total mismatch on orders: {mismatches[:5]}"

    def test_all_statuses_present(self, seeded_db):
        """With 1500 orders the weighted distribution should produce all 5 statuses."""
        statuses = {
            row[0] for row in seeded_db.execute("SELECT DISTINCT status FROM orders")
        }
        assert statuses == set(seed_db.ORDER_STATUSES)

    def test_order_dates_in_range(self, seeded_db):
        """All order dates should fall between 2024-01-01 and 2025-07-01 (~545 days)."""
        min_date, max_date = seeded_db.execute(
            "SELECT MIN(order_date), MAX(order_date) FROM orders"
        ).fetchone()
        assert min_date >= "2024-01-01"
        assert max_date <= "2025-07-01"

    def test_order_items_quantity_positive(self, seeded_db):
        min_qty = seeded_db.execute("SELECT MIN(quantity) FROM order_items").fetchone()[0]
        assert min_qty >= 1

    def test_no_duplicate_product_per_order(self, seeded_db):
        """UNIQUE(order_id, product_id) should be enforced — verify no dupes in data."""
        dupes = seeded_db.execute("""
            SELECT order_id, product_id, COUNT(*) AS cnt
            FROM order_items
            GROUP BY order_id, product_id
            HAVING cnt > 1
        """).fetchall()
        assert dupes == []

    def test_all_order_customer_fks_valid(self, seeded_db):
        orphans = seeded_db.execute("""
            SELECT o.order_id FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.customer_id
            WHERE c.customer_id IS NULL
        """).fetchall()
        assert orphans == []

    def test_all_order_item_product_fks_valid(self, seeded_db):
        orphans = seeded_db.execute("""
            SELECT oi.item_id FROM order_items oi
            LEFT JOIN products p ON oi.product_id = p.product_id
            WHERE p.product_id IS NULL
        """).fetchall()
        assert orphans == []
