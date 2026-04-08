"""
Tests for agent.py — LangChain SQL agent logic.

Strategy:
  - Unit tests mock the LLM/API so they run without an OPENAI_API_KEY.
  - Tests verify wiring: database connection, prompt content, error handling,
    ask() message assembly, and conversation history replay.
  - No live API calls — fast, free, deterministic.
"""

import os
import sqlite3
import random
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seed_db
import agent as agent_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_db_file(tmp_path):
    """Create a seeded SQLite database file and return its path."""
    db_path = tmp_path / "test_ecommerce.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    random.seed(42)
    seed_db.create_tables(conn)
    customer_ids = seed_db.seed_customers(conn)
    product_ids = seed_db.seed_categories_and_products(conn)
    seed_db.seed_orders(conn, customer_ids, product_ids)
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Database connection tests
# ---------------------------------------------------------------------------

class TestGetDatabase:
    """Test get_database() — the SQLDatabase wrapper."""

    def test_connects_to_existing_db(self, seeded_db_file):
        """Should return a SQLDatabase instance connected to the file."""
        db = agent_module.get_database(seeded_db_file)
        assert db is not None
        # Should see all 5 tables
        tables = db.get_usable_table_names()
        assert set(tables) == {"customers", "categories", "products", "orders", "order_items"}

    def test_raises_on_missing_db(self, tmp_path):
        """Should raise FileNotFoundError if the database file doesn't exist."""
        fake_path = tmp_path / "nonexistent.db"
        with pytest.raises(FileNotFoundError, match="Run 'python seed_db.py' first"):
            agent_module.get_database(fake_path)

    def test_sample_rows_included(self, seeded_db_file):
        """The table info should include sample rows for LLM context."""
        db = agent_module.get_database(seeded_db_file)
        table_info = db.get_table_info()
        # Should contain CREATE TABLE statements and sample data
        assert "CREATE TABLE" in table_info
        assert "customers" in table_info


# ---------------------------------------------------------------------------
# Agent creation tests
# ---------------------------------------------------------------------------

class TestCreateAgent:
    """Test create_agent() — agent wiring and configuration."""

    def test_raises_without_api_key(self, seeded_db_file):
        """Should raise EnvironmentError if OPENAI_API_KEY is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Also clear any cached dotenv values
            with patch.object(agent_module, "load_dotenv"):
                # Reload won't help; just patch os.getenv
                with patch("agent.os.getenv", return_value=None):
                    with pytest.raises(EnvironmentError, match="OPENAI_API_KEY not set"):
                        agent_module.create_agent(db_path=seeded_db_file)

    @patch("agent.create_react_agent")
    @patch("agent.SQLDatabaseToolkit")
    @patch("agent.ChatOpenAI")
    @patch("agent.os.getenv", return_value="sk-test-fake-key-123")
    def test_creates_agent_with_correct_model(
        self, mock_getenv, mock_llm_cls, mock_toolkit_cls, mock_create_agent, seeded_db_file
    ):
        """Should pass the model name to ChatOpenAI and temperature=0."""
        mock_toolkit_instance = MagicMock()
        mock_toolkit_instance.get_tools.return_value = [MagicMock()]
        mock_toolkit_cls.return_value = mock_toolkit_instance
        mock_create_agent.return_value = MagicMock()

        agent_module.create_agent(db_path=seeded_db_file, model="gpt-4o-mini")

        mock_llm_cls.assert_called_once_with(model="gpt-4o-mini", temperature=0)

    @patch("agent.create_react_agent")
    @patch("agent.SQLDatabaseToolkit")
    @patch("agent.ChatOpenAI")
    @patch("agent.os.getenv", return_value="sk-test-fake-key-123")
    def test_passes_system_prompt_to_agent(
        self, mock_getenv, mock_llm_cls, mock_toolkit_cls, mock_create_agent, seeded_db_file
    ):
        """The system prompt should instruct the LLM to be a SQL analyst."""
        mock_toolkit_instance = MagicMock()
        mock_toolkit_instance.get_tools.return_value = [MagicMock()]
        mock_toolkit_cls.return_value = mock_toolkit_instance
        mock_create_agent.return_value = MagicMock()

        agent_module.create_agent(db_path=seeded_db_file)

        # Verify create_react_agent was called with the system prompt
        call_args = mock_create_agent.call_args
        prompt_arg = call_args.kwargs.get("prompt") or call_args[1].get("prompt")
        if prompt_arg is None:
            # Might be positional
            prompt_arg = call_args[0][2] if len(call_args[0]) > 2 else None
        assert prompt_arg is not None
        assert "data analyst" in prompt_arg.content.lower()

    @patch("agent.create_react_agent")
    @patch("agent.SQLDatabaseToolkit")
    @patch("agent.ChatOpenAI")
    @patch("agent.os.getenv", return_value="sk-test-fake-key-123")
    def test_toolkit_gets_sql_tools(
        self, mock_getenv, mock_llm_cls, mock_toolkit_cls, mock_create_agent, seeded_db_file
    ):
        """The agent should receive tools from SQLDatabaseToolkit."""
        mock_tools = [MagicMock(name="sql_db_query"), MagicMock(name="sql_db_schema")]
        mock_toolkit_instance = MagicMock()
        mock_toolkit_instance.get_tools.return_value = mock_tools
        mock_toolkit_cls.return_value = mock_toolkit_instance
        mock_create_agent.return_value = MagicMock()

        agent_module.create_agent(db_path=seeded_db_file)

        # Verify the agent was created with the toolkit's tools
        call_args = mock_create_agent.call_args
        tools_arg = call_args[0][1]  # second positional arg
        assert tools_arg == mock_tools


# ---------------------------------------------------------------------------
# System prompt content tests
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    """Verify the system prompt contains essential instructions."""

    def test_contains_readonly_instruction(self):
        assert "NEVER" in agent_module.SYSTEM_PROMPT
        assert "INSERT" in agent_module.SYSTEM_PROMPT or "DML" in agent_module.SYSTEM_PROMPT

    def test_contains_limit_instruction(self):
        assert "LIMIT" in agent_module.SYSTEM_PROMPT

    def test_contains_error_retry_instruction(self):
        assert "retry" in agent_module.SYSTEM_PROMPT.lower()

    def test_contains_schema_check_instruction(self):
        assert "schema" in agent_module.SYSTEM_PROMPT.lower()

    def test_contains_scope_guardrail(self):
        """System prompt should instruct the agent to only answer data-related questions."""
        prompt_lower = agent_module.SYSTEM_PROMPT.lower()
        assert "unrelated" in prompt_lower or "only answer" in prompt_lower
        assert "general-purpose" in prompt_lower or "redirect" in prompt_lower


# ---------------------------------------------------------------------------
# ask() function tests
# ---------------------------------------------------------------------------

class TestAsk:
    """Test ask() — message assembly and response extraction."""

    def test_sends_question_as_human_message(self):
        """The question should be sent as the last HumanMessage."""
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="The top product is Widget A.")]
        }

        result = agent_module.ask(mock_agent, "What is the top product?")

        # Check the messages sent to the agent
        call_args = mock_agent.invoke.call_args[0][0]
        messages = call_args["messages"]
        assert len(messages) == 1
        assert messages[0].content == "What is the top product?"

    def test_returns_output_from_last_message(self):
        """ask() should return the content of the last AI message."""
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="Revenue is $12,345.67")]
        }

        result = agent_module.ask(mock_agent, "Total revenue?")
        assert result["output"] == "Revenue is $12,345.67"

    def test_includes_history_as_messages(self):
        """Conversation history should be replayed as Human/AI message pairs."""
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="Filtered results...")]
        }

        history = [
            ("What are the top products?", "Here are the top 5 products..."),
            ("Sort by category", "Here they are sorted by category..."),
        ]

        agent_module.ask(mock_agent, "Now filter by Q4", history=history)

        call_args = mock_agent.invoke.call_args[0][0]
        messages = call_args["messages"]
        # 2 history pairs (4 messages) + 1 new question = 5 messages
        assert len(messages) == 5
        assert messages[0].content == "What are the top products?"
        assert messages[1].content == "Here are the top 5 products..."
        assert messages[2].content == "Sort by category"
        assert messages[3].content == "Here they are sorted by category..."
        assert messages[4].content == "Now filter by Q4"

    def test_empty_history_sends_only_question(self):
        """Empty history list should behave the same as None."""
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="Answer")]
        }

        agent_module.ask(mock_agent, "Test question", history=[])

        call_args = mock_agent.invoke.call_args[0][0]
        messages = call_args["messages"]
        assert len(messages) == 1

    def test_none_history_sends_only_question(self):
        """None history should send only the question."""
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [MagicMock(content="Answer")]
        }

        agent_module.ask(mock_agent, "Test question", history=None)

        call_args = mock_agent.invoke.call_args[0][0]
        messages = call_args["messages"]
        assert len(messages) == 1


# ---------------------------------------------------------------------------
# Default configuration tests
# ---------------------------------------------------------------------------

class TestDefaults:
    """Verify default values and paths."""

    def test_default_db_path_points_to_data_folder(self):
        """DEFAULT_DB_PATH should end with data/ecommerce.db."""
        assert agent_module.DEFAULT_DB_PATH.name == "ecommerce.db"
        assert agent_module.DEFAULT_DB_PATH.parent.name == "data"

    def test_default_model_is_gpt4o_mini(self):
        """The default model in create_agent signature should be gpt-4o-mini."""
        import inspect

        sig = inspect.signature(agent_module.create_agent)
        assert sig.parameters["model"].default == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Read-only guard tests
# ---------------------------------------------------------------------------

class TestReadOnlyGuard:
    """Verify the database connection is read-only at the engine level."""

    def test_insert_blocked(self, seeded_db_file):
        """INSERT should fail on the read-only connection."""
        db = agent_module.get_database(seeded_db_file)
        with pytest.raises(Exception):
            db.run("INSERT INTO customers (name, email, city, state) VALUES ('Hacker', 'h@h.com', 'NYC', 'NY')")

    def test_drop_blocked(self, seeded_db_file):
        """DROP TABLE should fail on the read-only connection."""
        db = agent_module.get_database(seeded_db_file)
        with pytest.raises(Exception):
            db.run("DROP TABLE customers")

    def test_delete_blocked(self, seeded_db_file):
        """DELETE should fail on the read-only connection."""
        db = agent_module.get_database(seeded_db_file)
        with pytest.raises(Exception):
            db.run("DELETE FROM customers")

    def test_update_blocked(self, seeded_db_file):
        """UPDATE should fail on the read-only connection."""
        db = agent_module.get_database(seeded_db_file)
        with pytest.raises(Exception):
            db.run("UPDATE customers SET name = 'Hacked' WHERE id = 1")

    def test_select_still_works(self, seeded_db_file):
        """SELECT queries should still work on the read-only connection."""
        db = agent_module.get_database(seeded_db_file)
        result = db.run("SELECT COUNT(*) FROM customers")
        assert result
