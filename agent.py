"""
LangChain SQL agent: converts natural language questions into SQL queries.

Architecture:
  - Uses LangChain's SQLDatabaseToolkit to introspect the SQLite schema
    (table names, column types, sample rows) so the LLM can write accurate SQL.
  - The agent is a ReAct-style reasoning loop: it thinks about what SQL to
    write, executes it, inspects the result, and formulates a human answer.
  - Conversation memory (ChatMessageHistory) allows follow-up questions
    like "now filter that by Q4" referencing prior context.

Usage:
  from agent import create_agent, ask

  agent = create_agent()             # uses default DB path
  response = ask(agent, "What are the top 5 products by revenue?")
  print(response["output"])
"""

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

# ---------------------------------------------------------------------------
# Load environment variables (.env file must contain OPENAI_API_KEY)
# ---------------------------------------------------------------------------
load_dotenv()

# Default database path: data/ecommerce.db relative to this file
DEFAULT_DB_PATH = Path(__file__).parent / "data" / "ecommerce.db"

# ---------------------------------------------------------------------------
# System prompt: tells the LLM how to behave as a SQL analyst
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a senior data analyst agent with access to an
e-commerce SQLite database.  Your job is to answer business questions by
writing and executing SQL queries.

Rules:
1. ALWAYS look at the table schemas before writing a query.
2. ALWAYS check your query for correctness before executing.
3. Use LIMIT to avoid returning too many rows (default: 20).
4. If the question is ambiguous, state your assumptions clearly.
5. After getting query results, provide a clear, concise human-readable answer.
6. If a query fails, diagnose the error and retry with a corrected query.
7. NEVER make DML statements (INSERT, UPDATE, DELETE, DROP, etc.).
8. Format numbers nicely (e.g., $1,234.56 for currency, commas for counts).
9. When relevant, suggest follow-up questions the user could ask.
10. ONLY answer questions related to the e-commerce database, SQL, or data
    analysis. If the user asks about unrelated topics (e.g., weather, coding
    help, general knowledge, personal advice), politely decline and redirect
    them to ask a data-related question instead. You are a data analyst, not
    a general-purpose assistant.
"""


def get_database(db_path: Path = DEFAULT_DB_PATH) -> SQLDatabase:
    """
    Connect to the SQLite database and return a LangChain SQLDatabase wrapper.

    The wrapper introspects all tables, columns, types, and sample rows,
    which the LLM uses to write accurate SQL.
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run 'python seed_db.py' first."
        )
    db_path_str = str(db_path)
    return SQLDatabase.from_uri(
        f"sqlite:///{db_path}",
        sample_rows_in_table_info=3,  # show 3 example rows per table
        engine_args={
            "creator": lambda: sqlite3.connect(
                f"file:{db_path_str}?mode=ro", uri=True
            )
        },
    )


def create_agent(db_path: Path = DEFAULT_DB_PATH, model: str = "gpt-4o-mini"):
    """
    Create a ReAct SQL agent with tools to query the database.

    Args:
        db_path: Path to the SQLite database file.
        model:   OpenAI model name.  gpt-4o-mini is fast and cheap;
                 upgrade to gpt-4o for complex multi-join queries.

    Returns:
        A LangGraph CompiledGraph you can invoke with messages.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY not set. Copy .env.example to .env and add your key."
        )

    # LLM: temperature=0 for deterministic, repeatable SQL generation
    llm = ChatOpenAI(model=model, temperature=0)

    # Database connection + toolkit (gives the agent SQL tools)
    db = get_database(db_path)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    tools = toolkit.get_tools()

    # Build a ReAct agent: LLM reasons → picks a tool → observes → repeats
    agent = create_react_agent(
        llm,
        tools,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )

    return agent


def ask(agent, question: str, history: list = None) -> dict:
    """
    Send a natural language question to the agent and get a response.

    Args:
        agent:    The compiled agent from create_agent().
        question: A natural language question (e.g., "Top 5 products by revenue?").
        history:  Optional list of prior (question, answer) tuples for
                  multi-turn conversation context.

    Returns:
        dict with "output" (str) = the agent's final answer.
    """
    messages = []

    # Replay conversation history so the agent can handle follow-ups
    if history:
        for user_msg, ai_msg in history:
            messages.append(HumanMessage(content=user_msg))
            messages.append(AIMessage(content=ai_msg))

    messages.append(HumanMessage(content=question))

    # Invoke the agent and extract the final AI message
    result = agent.invoke({"messages": messages})
    final_message = result["messages"][-1]

    return {"output": final_message.content}
