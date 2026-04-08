"""
Streamlit chat interface for the NL-SQL Agent.

Provides a conversational UI where users type natural language questions
and receive SQL-powered answers from the LangChain agent.  Conversation
history is maintained in Streamlit session state so the agent can handle
follow-up questions (e.g., "now group that by month").
"""

import streamlit as st
from agent import create_agent, ask

# ---------------------------------------------------------------------------
# Page configuration
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="NL → SQL Agent",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS for a polished look
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* ---- Global ---- */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* ---- Header area ---- */
    .hero-title {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
    .hero-subtitle {
        font-size: 1.05rem;
        color: #6b7280;
        margin-top: 0;
        margin-bottom: 1.5rem;
    }

    /* ---- Sidebar ---- */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e1e2e 0%, #2d2b55 100%);
    }
    section[data-testid="stSidebar"] * {
        color: #e2e8f0 !important;
    }
    section[data-testid="stSidebar"] .stButton > button {
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 8px;
        color: #e2e8f0 !important;
        font-size: 0.85rem;
        text-align: left;
        padding: 0.55rem 0.8rem;
        transition: all 0.2s ease;
    }
    section[data-testid="stSidebar"] .stButton > button:hover {
        background: rgba(255,255,255,0.15);
        border-color: #667eea;
        transform: translateX(3px);
    }

    /* ---- Stat cards ---- */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1rem 1.2rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    div[data-testid="stMetric"] label {
        color: #6b7280 !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #1e293b !important;
        font-weight: 700 !important;
    }

    /* ---- Chat messages ---- */
    div[data-testid="stChatMessage"] {
        border-radius: 12px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.5rem;
    }

    /* ---- Welcome card (empty state) ---- */
    .welcome-card {
        background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%);
        border: 1px solid #667eea30;
        border-radius: 16px;
        padding: 2.5rem 2rem;
        text-align: center;
        margin: 2rem auto;
        max-width: 600px;
    }
    .welcome-card h3 { color: #334155; margin-bottom: 0.5rem; }
    .welcome-card p { color: #64748b; font-size: 0.95rem; }
    .feature-row {
        display: flex;
        justify-content: center;
        gap: 2rem;
        margin-top: 1.5rem;
    }
    .feature-item {
        text-align: center;
        padding: 0.5rem;
    }
    .feature-icon { font-size: 1.5rem; margin-bottom: 0.3rem; }
    .feature-label { font-size: 0.82rem; color: #64748b; }

    /* ---- Footer ---- */
    .app-footer {
        text-align: center;
        padding: 1.5rem 0 0.5rem;
        color: #94a3b8;
        font-size: 0.78rem;
        border-top: 1px solid #f1f5f9;
        margin-top: 2rem;
    }

    /* ---- Chat input ---- */
    div[data-testid="stChatInput"] textarea {
        border-radius: 12px !important;
    }

    /* ---- Hide default Streamlit branding ---- */
    #MainMenu, footer, header { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar: project info and example queries
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🔍 NL → SQL Agent")
    st.markdown(
        "<span style='font-size:0.88rem; color:#a0aec0;'>"
        "Ask plain-English questions about an e-commerce database "
        "and get instant answers powered by LangChain + GPT."
        "</span>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    st.markdown("#### 🎯 Demo Script")
    st.markdown(
        "<span style='font-size:0.78rem; color:#718096;'>Run in order for best showcase</span>",
        unsafe_allow_html=True,
    )
    demo_questions = [
        ("1️⃣", "What are the top 5 products by total revenue?"),
        ("2️⃣", "Now break that down by month"),
        ("3️⃣", "Which customers placed the most orders but have the lowest average order value? Show the top 10."),
        ("4️⃣", "Delete all cancelled orders"),
        ("5️⃣", "What interesting patterns do you see in the order data? Any seasonality or trends?"),
    ]
    for icon, q in demo_questions:
        if st.button(f"{icon}  {q}", key=q, use_container_width=True):
            st.session_state["pending_question"] = q

    st.markdown("---")
    st.markdown("#### 💡 Bonus Questions")
    bonus_questions = [
        "What's the return rate by product category?",
        "Which state has the highest revenue per customer?",
        "Compare Q1 2024 vs Q1 2025 — which categories grew?",
        "Are there any customers who signed up but never placed an order?",
    ]
    for q in bonus_questions:
        if st.button(q, key=q, use_container_width=True):
            st.session_state["pending_question"] = q

    st.markdown("---")

    # Clear chat button
    if st.button("🗑️  Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.history_pairs = []
        st.rerun()

    st.markdown("---")
    st.markdown(
        "<div style='text-align:center; font-size:0.75rem; color:#718096;'>"
        "Built with LangChain · Streamlit · SQLite<br>"
        "Model: GPT-4o-mini · Read-only DB"
        "</div>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Initialize session state
# ---------------------------------------------------------------------------
# Chat history: list of {"role": "user"|"assistant", "content": str}
if "messages" not in st.session_state:
    st.session_state.messages = []

# Conversation pairs for agent memory: list of (user_msg, ai_msg) tuples
if "history_pairs" not in st.session_state:
    st.session_state.history_pairs = []

# Cache the agent so it's created once per session, not on every rerun
if "agent" not in st.session_state:
    try:
        st.session_state.agent = create_agent()
    except (EnvironmentError, FileNotFoundError) as e:
        st.error(str(e))
        st.stop()

# ---------------------------------------------------------------------------
# Main chat area — header
# ---------------------------------------------------------------------------
st.markdown('<p class="hero-title">NL → SQL Agent</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="hero-subtitle">'
    "Ask natural-language questions about an e-commerce database — "
    "powered by a ReAct agent with conversation memory"
    "</p>",
    unsafe_allow_html=True,
)

# Stats bar
col1, col2, col3, col4 = st.columns(4)
col1.metric("Tables", "5")
col2.metric("Products", "64")
col3.metric("Orders", "1,500")
col4.metric("Customers", "200")

st.markdown("")  # spacer

# ---------------------------------------------------------------------------
# Welcome card (empty state)
# ---------------------------------------------------------------------------
if not st.session_state.messages:
    st.markdown(
        """
        <div class="welcome-card">
            <h3>👋 Welcome!</h3>
            <p>
                Type a question below or click a demo query in the sidebar
                to start exploring the e-commerce dataset.
            </p>
            <div class="feature-row">
                <div class="feature-item">
                    <div class="feature-icon">💬</div>
                    <div class="feature-label">Natural language<br>queries</div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">🧠</div>
                    <div class="feature-label">Conversation<br>memory</div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">🛡️</div>
                    <div class="feature-label">Read-only<br>guardrails</div>
                </div>
                <div class="feature-item">
                    <div class="feature-icon">⚡</div>
                    <div class="feature-label">Multi-step<br>reasoning</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Render chat history
# ---------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# Handle user input (typed or clicked from sidebar)
# ---------------------------------------------------------------------------
user_input = st.chat_input("Ask a question about the data...")

# If the user clicked an example question, use that instead
if "pending_question" in st.session_state:
    user_input = st.session_state.pop("pending_question")

if user_input:
    # Display user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Get agent response
    with st.chat_message("assistant"):
        with st.spinner("🔍 Querying the database..."):
            try:
                response = ask(
                    st.session_state.agent,
                    user_input,
                    history=st.session_state.history_pairs[-10:],
                )
                answer = response["output"]
            except Exception as e:
                answer = f"⚠️ Error: {e}"

        st.markdown(answer)

    # Save to chat history and conversation memory
    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.session_state.history_pairs.append((user_input, answer))

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
if st.session_state.messages:
    st.markdown(
        '<div class="app-footer">'
        f"💬 {len(st.session_state.messages) // 2} exchanges · "
        f"🧠 {min(len(st.session_state.history_pairs), 10)} turns in memory · "
        "🛡️ Read-only mode"
        "</div>",
        unsafe_allow_html=True,
    )
