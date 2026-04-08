"""
Seed script: creates and populates an e-commerce SQLite database.

Design decisions:
  - STRICT tables enforce column types at insert/update time, making
    SQLite behave like PostgreSQL/MySQL (requires SQLite >= 3.37).
  - Foreign keys + CHECK constraints ensure referential integrity and
    valid values (e.g., quantity > 0, price >= 0).
  - Indexes are added on columns used in common analytical queries
    (dates, foreign keys, status) to keep the agent's queries fast.
  - random.seed(42) makes the fake data fully reproducible.

Design trade-offs (reviewed & defended):
  - REAL for prices: SQLite has no DECIMAL type.  Values are round()ed to
    2 decimal places on write, acceptable for analytical (not ledger) use.
  - Dates as TEXT: SQLite has no native DATE.  ISO 8601 strings are the
    officially recommended format; seed script uses strftime() to guarantee
    correctness.
  - No ON DELETE CASCADE on FKs: financial records should never be silently
    deleted.  The default NO ACTION (= RESTRICT) is the safest choice.
  - No composite indexes: at ~1 500 rows, single-column indexes are
    sufficient.  Add composites when scaling past 1 M rows.
  - stock_qty is a point-in-time snapshot for analytical queries, not a
    live inventory counter.

Usage:
    python seed_db.py          # creates data/ecommerce.db
"""

import sqlite3
import random
from datetime import datetime, timedelta
from pathlib import Path

# Database lives inside the data/ subfolder, next to this script
DB_PATH = Path(__file__).parent / "data" / "ecommerce.db"

# ---------------------------------------------------------------------------
# Realistic fake-data pools
# Names are intentionally diverse to reflect real-world customer bases.
# ---------------------------------------------------------------------------
FIRST_NAMES = [
    "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason",
    "Isabella", "James", "Mia", "Alexander", "Charlotte", "Benjamin", "Amelia",
    "Lucas", "Harper", "Henry", "Evelyn", "Daniel", "Priya", "Raj", "Mei",
    "Carlos", "Fatima", "Yuki", "Omar", "Aisha", "Wei", "Kenji",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Anderson", "Taylor", "Thomas", "Moore",
    "Jackson", "Patel", "Kim", "Nguyen", "Chen", "Yamamoto", "Singh", "Ahmed",
    "Lopez", "Gonzalez", "Wilson", "Lee", "Walker", "Hall", "Allen", "Young",
]

# (city, state) tuples — state is always 2 chars, enforced by CHECK constraint
CITIES = [
    ("Seattle", "WA"), ("Portland", "OR"), ("San Francisco", "CA"),
    ("Los Angeles", "CA"), ("New York", "NY"), ("Chicago", "IL"),
    ("Austin", "TX"), ("Denver", "CO"), ("Boston", "MA"), ("Miami", "FL"),
    ("Phoenix", "AZ"), ("Atlanta", "GA"), ("Nashville", "TN"),
    ("Minneapolis", "MN"), ("San Diego", "CA"),
]

# 8 product categories — broad enough for interesting analytical queries
CATEGORIES = [
    "Electronics", "Clothing", "Home & Kitchen", "Books",
    "Sports & Outdoors", "Beauty", "Toys & Games", "Grocery",
]

# Each category has 8 products with realistic price points.
# Dict structure: { category_name: [(product_name, price), ...] }
PRODUCTS = {
    "Electronics": [
        ("Wireless Earbuds", 49.99), ("USB-C Hub", 34.99),
        ("Mechanical Keyboard", 89.99), ("Webcam HD", 59.99),
        ("Portable Charger", 29.99), ("Smart Watch", 199.99),
        ("Bluetooth Speaker", 39.99), ("Laptop Stand", 44.99),
    ],
    "Clothing": [
        ("Cotton T-Shirt", 19.99), ("Denim Jeans", 49.99),
        ("Running Shoes", 79.99), ("Winter Jacket", 129.99),
        ("Baseball Cap", 14.99), ("Wool Socks 3-Pack", 12.99),
        ("Hoodie", 39.99), ("Yoga Pants", 34.99),
    ],
    "Home & Kitchen": [
        ("French Press", 24.99), ("Cutting Board Set", 19.99),
        ("Cast Iron Skillet", 34.99), ("Kitchen Scale", 14.99),
        ("Vacuum Insulated Bottle", 27.99), ("Dish Towel Set", 9.99),
        ("Air Fryer", 89.99), ("Coffee Grinder", 29.99),
    ],
    "Books": [
        ("Python Crash Course", 29.99), ("Designing Data Apps", 44.99),
        ("SQL Pocket Guide", 14.99), ("Atomic Habits", 16.99),
        ("The Lean Startup", 19.99), ("Deep Work", 17.99),
        ("Storytelling with Data", 24.99), ("Thinking Fast and Slow", 15.99),
    ],
    "Sports & Outdoors": [
        ("Yoga Mat", 24.99), ("Resistance Bands Set", 19.99),
        ("Hiking Backpack", 69.99), ("Water Bottle", 14.99),
        ("Jump Rope", 9.99), ("Foam Roller", 22.99),
        ("Camping Lantern", 19.99), ("Bike Light Set", 24.99),
    ],
    "Beauty": [
        ("Moisturizer SPF 30", 18.99), ("Lip Balm Set", 8.99),
        ("Face Wash", 12.99), ("Sunscreen SPF 50", 14.99),
        ("Hair Oil", 11.99), ("Hand Cream", 9.99),
        ("Eye Cream", 24.99), ("Body Lotion", 13.99),
    ],
    "Toys & Games": [
        ("Board Game Classic", 24.99), ("Puzzle 1000pc", 14.99),
        ("Card Game Pack", 9.99), ("Building Blocks Set", 34.99),
        ("Remote Control Car", 29.99), ("Stuffed Animal", 12.99),
        ("Science Kit", 19.99), ("Art Supply Set", 22.99),
    ],
    "Grocery": [
        ("Organic Coffee Beans", 14.99), ("Trail Mix Variety", 11.99),
        ("Dark Chocolate Bar", 4.99), ("Olive Oil 500ml", 9.99),
        ("Protein Bars 12pk", 24.99), ("Green Tea Box", 7.99),
        ("Pasta Sampler", 8.99), ("Hot Sauce Trio", 15.99),
    ],
}

# Status values must match the CHECK constraint in the orders table
ORDER_STATUSES = ["completed", "processing", "shipped", "cancelled", "returned"]


def create_tables(conn: sqlite3.Connection) -> None:
    """
    Create 5 normalized tables (3NF) with STRICT mode.

    Schema:
        customers  ──< orders ──< order_items >── products >── categories

    STRICT enforces that every value matches the declared column type.
    CHECK constraints add business-rule validation on top.
    """
    # Drop in reverse dependency order to avoid FK conflicts
    conn.executescript("""
        DROP TABLE IF EXISTS order_items;
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS categories;
        DROP TABLE IF EXISTS customers;

        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            first_name  TEXT NOT NULL,
            last_name   TEXT NOT NULL,
            email       TEXT NOT NULL UNIQUE,
            city        TEXT NOT NULL,
            state       TEXT NOT NULL CHECK (length(state) = 2),
            created_at  TEXT NOT NULL
        ) STRICT;

        CREATE TABLE categories (
            category_id   INTEGER PRIMARY KEY,
            category_name TEXT NOT NULL UNIQUE
        ) STRICT;

        CREATE TABLE products (
            product_id   INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL,
            category_id  INTEGER NOT NULL REFERENCES categories(category_id),
            -- REAL (not INTEGER cents) because SQLite has no DECIMAL type.
            -- Values are round()ed to 2 dp on write; acceptable for analytics.
            price        REAL NOT NULL CHECK (price >= 0),
            -- Snapshot for analytical queries (e.g. "low-stock products"),
            -- not a live counter decremented on each order.
            stock_qty    INTEGER NOT NULL DEFAULT 100 CHECK (stock_qty >= 0)
        ) STRICT;

        CREATE TABLE orders (
            order_id    INTEGER PRIMARY KEY,
            -- NO ACTION (default) on FK = safest for financial data.
            -- Customers are never hard-deleted in production; orders must
            -- survive even if the customer record is deactivated.
            customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
            -- TEXT in ISO 8601 format — SQLite's officially recommended
            -- date storage.  Seed script uses strftime() to guarantee format.
            order_date  TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'processing'
                        CHECK (status IN ('completed','processing','shipped','cancelled','returned')),
            -- Denormalized: computed from SUM(qty * unit_price) in order_items
            -- at seed time.  Avoids an expensive JOIN+GROUP BY on every read.
            -- Safe because this DB is single-load, read-only after seeding.
            total       REAL NOT NULL DEFAULT 0.0 CHECK (total >= 0)
        ) STRICT;

        CREATE TABLE order_items (
            item_id    INTEGER PRIMARY KEY,
            order_id   INTEGER NOT NULL REFERENCES orders(order_id),
            product_id INTEGER NOT NULL REFERENCES products(product_id),
            quantity   INTEGER NOT NULL CHECK (quantity > 0),
            unit_price REAL NOT NULL CHECK (unit_price >= 0),
            -- A given product should appear at most once per order.
            -- The seed script already uses random.sample() to guarantee this,
            -- but the schema should be self-defending — not rely on app code.
            UNIQUE (order_id, product_id)
        ) STRICT;

        -- Indexes speed up the most common analytical query patterns:
        --   "show me orders for customer X"  → idx_orders_customer
        --   "revenue by month"               → idx_orders_date
        --   "all completed orders"            → idx_orders_status
        --   "line items for order #123"       → idx_order_items_order
        --   "products in Electronics"         → idx_products_category
        CREATE INDEX idx_orders_customer   ON orders(customer_id);
        CREATE INDEX idx_orders_date       ON orders(order_date);
        CREATE INDEX idx_orders_status     ON orders(status);
        CREATE INDEX idx_order_items_order ON order_items(order_id);
        CREATE INDEX idx_products_category ON products(category_id);
    """)


def seed_customers(conn: sqlite3.Connection, n: int = 200) -> list[int]:
    """
    Generate n fake customers with unique emails.

    Returns a list of customer IDs for use when generating orders.
    Emails are made unique by appending the customer index.
    """
    customers = []
    emails_seen: set[str] = set()  # guard against collisions
    base_date = datetime(2023, 1, 1)  # earliest possible signup date

    for i in range(1, n + 1):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        if email in emails_seen:
            email = f"{first.lower()}.{last.lower()}{i + 1000}@example.com"
        emails_seen.add(email)
        city, state = random.choice(CITIES)
        created = base_date + timedelta(days=random.randint(0, 700))
        customers.append((i, first, last, email, city, state, created.strftime("%Y-%m-%d")))

    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?)", customers
    )
    return [c[0] for c in customers]


def seed_categories_and_products(conn: sqlite3.Connection) -> list[int]:
    """
    Insert all categories and their products from the data pools above.

    Returns a list of product IDs for use when generating order items.
    """
    product_ids = []
    pid = 1  # auto-increment product IDs manually for determinism
    for cid, cat_name in enumerate(CATEGORIES, start=1):
        conn.execute("INSERT INTO categories VALUES (?, ?)", (cid, cat_name))
        for name, price in PRODUCTS[cat_name]:
            stock = random.randint(20, 500)
            conn.execute(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?)",
                (pid, name, cid, price, stock),
            )
            product_ids.append(pid)
            pid += 1
    return product_ids


def seed_orders(
    conn: sqlite3.Connection,
    customer_ids: list[int],
    product_ids: list[int],
    n_orders: int = 1500,
) -> None:
    """
    Generate fake orders spanning ~18 months (Jan 2024 – Jul 2025).

    Each order has 1-5 randomly selected products. Order totals are
    computed from (quantity * unit_price) across all line items.

    Status distribution is weighted to mimic reality:
      completed=60%, shipped=15%, processing=10%, cancelled=10%, returned=5%
    """
    base_date = datetime(2024, 1, 1)

    # Pre-load product prices into a dict for fast lookup
    prices: dict[int, float] = {}
    for row in conn.execute("SELECT product_id, price FROM products"):
        prices[row[0]] = row[1]

    for oid in range(1, n_orders + 1):
        cust = random.choice(customer_ids)
        order_date = base_date + timedelta(days=random.randint(0, 545))
        # Weighted random status — most orders complete successfully
        status = random.choices(
            ORDER_STATUSES, weights=[60, 10, 15, 10, 5], k=1
        )[0]

        conn.execute(
            "INSERT INTO orders (order_id, customer_id, order_date, status, total) VALUES (?, ?, ?, ?, 0.0)",
            (oid, cust, order_date.strftime("%Y-%m-%d"), status),
        )

        # Each order gets 1-5 distinct products (no duplicate line items)
        n_items = random.randint(1, 5)
        chosen = random.sample(product_ids, n_items)
        order_total = 0.0

        for pid in chosen:
            qty = random.randint(1, 4)
            unit_price = prices[pid]
            order_total += qty * unit_price
            conn.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                (oid, pid, qty, unit_price),
            )

        conn.execute(
            "UPDATE orders SET total = ? WHERE order_id = ?",
            (round(order_total, 2), oid),
        )


def main() -> None:
    """Entry point: creates a fresh database and populates it with fake data."""
    # Ensure the data/ directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Start fresh every run — safe because this is generated data
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")    # faster writes, safe for reads
    conn.execute("PRAGMA foreign_keys=ON")     # enforce FK constraints

    random.seed(42)  # deterministic — same data every run

    create_tables(conn)
    customer_ids = seed_customers(conn)
    product_ids = seed_categories_and_products(conn)
    seed_orders(conn, customer_ids, product_ids)

    conn.commit()

    # Print row counts as a sanity check
    print("Seeded tables:")
    for table in ["customers", "categories", "products", "orders", "order_items"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")

    print(f"\nDatabase created at: {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()
