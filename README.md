# nl-sql-agent

An AI agent that converts natural language questions into SQL, executes them against an e-commerce database, and returns human-readable results. Built with LangChain, SQLite (STRICT mode), and Streamlit.

![Demo](assets/demo.gif)

## Tech Stack

- **Python 3.9+**
- **LangChain / LangGraph** — LLM orchestration and agent framework
- **SQLite (STRICT mode)** — type-enforced SQL database (Postgres-compatible schema)
- **Streamlit** — polished chat UI with conversation memory, demo script sidebar, and welcome dashboard
- **OpenAI API** — LLM backend (default: `gpt-4o-mini`)

## Architecture

```
User ──► Streamlit Chat UI (app.py)
              │
              ▼
         ask(agent, question, history)     ◄── agent.py
              │
              ▼
         LangGraph ReAct Agent
           ├─ SystemPrompt (SQL analyst rules)
           ├─ ChatOpenAI (gpt-4o-mini, temperature=0)
           └─ SQLDatabaseToolkit tools:
                ├─ sql_db_list_tables
                ├─ sql_db_schema
                ├─ sql_db_query
                └─ sql_db_query_checker
              │
              ▼
         SQLite (data/ecommerce.db)       ◄── seed_db.py
```

- **ReAct loop:** The agent reasons about what SQL to write, executes it via toolkit tools, inspects results, and formulates a human-readable answer.
- **Conversation memory:** Chat history is passed as `(user, assistant)` pairs so the agent handles follow-ups like "now group that by month".
- **Read-only guard:** Defense-in-depth — the system prompt forbids DML (Rule 7) *and* the SQLite connection is opened in read-only mode (`?mode=ro`) so even prompt injection can't mutate data.
- **Scope guardrail:** Rule 10 constrains the agent to data-related questions only — it declines weather, coding help, or general-knowledge queries.
- **History cap:** Only the last 10 conversation turns are sent as context, preventing token overflow on long sessions.

## Database Schema

5 normalized tables (3NF) with enforced types, foreign keys, CHECK constraints, and indexes:

```
customers ──< orders ──< order_items >── products >── categories
```

| Table | Rows | Description |
|---|---|---|
| `customers` | 200 | Name, email (unique), city/state, signup date |
| `categories` | 8 | Electronics, Clothing, Home & Kitchen, Books, Sports & Outdoors, Beauty, Toys & Games, Grocery |
| `products` | 64 | 8 products per category with realistic price points |
| `orders` | 1,500 | Spanning Jan 2024 – Jul 2025, weighted status distribution (60% completed, 15% shipped, 10% processing, 10% cancelled, 5% returned) |
| `order_items` | ~3,700 | 1–5 line items per order, quantity 1–4 |

**Design highlights:**
- `STRICT` tables enforce column types at insert/update (SQLite ≥ 3.37)
- `CHECK` constraints validate business rules (`quantity > 0`, `price >= 0`, `status IN (...)`, `length(state) = 2`)
- Indexes on `order_date`, `customer_id`, `status`, `order_id`, `category_id` for fast analytical queries
- `PRAGMA foreign_keys=ON` for referential integrity
- `random.seed(42)` makes all fake data fully reproducible

**Design trade-offs (reviewed & defended):**
| Decision | Rationale |
|---|---|
| `REAL` for prices (not INTEGER cents) | SQLite has no `DECIMAL` type; values are `round()`ed to 2 dp on write — acceptable for analytics, not ledger use |
| Dates as `TEXT` (ISO 8601) | SQLite has no native `DATE`; ISO 8601 strings are the [officially recommended format](https://www.sqlite.org/lang_datefmt.html) |
| `NO ACTION` on FK deletes | Financial records should never be silently cascade-deleted; safest default |
| No composite indexes | At ~1,500 rows single-column indexes are sufficient; add composites past 1M rows |
| `stock_qty` is a snapshot | Analytical column for queries like "low-stock products", not a live inventory counter |
| Denormalized `orders.total` | Precomputed from `order_items` at seed time to avoid JOIN+GROUP BY on every read; safe because DB is single-load, read-only after seeding |

## Testing

**75 tests** across three test files — run with:
```bash
python -m pytest tests/ -v
```

### Unit Tests (`tests/test_seed_db.py`) — 30 tests
| Test Class | What It Verifies |
|---|---|
| `TestDataPools` | Data pools are internally consistent (categories ↔ products, prices > 0, states = 2 chars) |
| `TestCreateTables` | All 5 tables exist, STRICT rejects wrong types, indexes created, idempotent |
| `TestSeedCustomers` | Correct count, unique emails, valid ISO dates, 2-char states |
| `TestSeedCategoriesAndProducts` | Correct counts, FK integrity, stock range |
| `TestSeedOrders` | Count, totals match line items, all statuses present, date range, no duplicate items |

### Integration Tests (`tests/test_integration.py`) — 21 tests
| Test Class | What It Verifies |
|---|---|
| `TestCheckConstraints` | Negative prices, zero qty, invalid status, negative stock/total, bad state length — all rejected |
| `TestForeignKeyEnforcement` | Orphan orders, products, items rejected; customer with orders can't be deleted |
| `TestUniqueConstraints` | Duplicate emails, categories, product-per-order — all rejected |
| `TestAnalyticalQueries` | Revenue by category, top customers, monthly orders, orders by city, avg order value |
| `TestReproducibility` | Two `seed(42)` databases produce identical data |
| `TestMainRoundTrip` | `main()` creates the file, is idempotent |

### Agent Tests (`tests/test_agent.py`) — 24 tests
| Test Class | Tests | What It Verifies |
|---|---|---|
| `TestGetDatabase` | 3 | Connects to existing DB, raises on missing file, includes sample rows in table info |
| `TestCreateAgent` | 4 | Raises without API key, passes correct model, system prompt wiring, toolkit tool injection |
| `TestSystemPrompt` | 5 | Contains read-only (no DML), LIMIT, retry, schema-check, and scope guardrail (Rule 10) instructions |
| `TestAsk` | 5 | Message assembly, response extraction, history replay as Human/AI pairs, empty/None history handling |
| `TestDefaults` | 2 | Default DB path points to `data/ecommerce.db`, default model is `gpt-4o-mini` |
| `TestReadOnlyGuard` | 5 | INSERT/DROP/DELETE/UPDATE blocked at DB level, SELECT still works |

All unit/integration tests use in-memory SQLite — no disk I/O, no API calls. Agent tests mock the LLM. Full suite runs in ~1 second.

## Project Structure

```
nl-sql-agent/
├── agent.py                  # LangChain ReAct SQL agent (create_agent, ask)
├── app.py                    # Streamlit chat UI with conversation memory & polished styling
├── seed_db.py                # Creates and populates the SQLite database
├── take_screenshots.py       # Playwright script to generate demo GIF frames
├── data/
│   └── ecommerce.db          # Generated database (not committed)
├── assets/
│   └── demo.gif              # Animated demo (6 frames, 30s loop)
├── tests/
│   ├── __init__.py
│   ├── conftest.py           # Shared fixtures (empty_conn, seeded_db)
│   ├── test_seed_db.py       # Unit tests for seed functions
│   ├── test_integration.py   # Integration tests (constraints, queries, reproducibility)
│   └── test_agent.py         # Agent unit tests (mocked LLM, no API calls)
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Setup

1. **Clone the repo:**
   ```bash
   git clone https://github.com/avantilikhite/nl-sql-agent.git
   cd nl-sql-agent
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Mac/Linux
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Seed the database:**
   ```bash
   python seed_db.py
   ```

5. **Set up your OpenAI API key:**
   ```bash
   cp .env.example .env
   # Edit .env and add your OPENAI_API_KEY
   ```

6. **Run the Streamlit app:**
   ```bash
   streamlit run app.py
   ```

## Demo Script

The sidebar includes a curated 5-question demo flow (run in order for best showcase):

| # | Question | What it demonstrates |
|---|---|---|
| 1️⃣ | "What are the top 5 products by total revenue?" | Multi-table JOIN + aggregation |
| 2️⃣ | "Now break that down by month" | Conversation memory (follow-up) |
| 3️⃣ | "Which customers placed the most orders but have the lowest average order value? Show the top 10." | Complex multi-metric ranking |
| 4️⃣ | "Delete all cancelled orders" | Safety guardrail (read-only refusal) |
| 5️⃣ | "What interesting patterns do you see in the order data? Any seasonality or trends?" | Autonomous multi-step reasoning |

Plus 4 bonus questions: return rate by category, revenue per customer by state, YoY category growth, and customers who never ordered.
