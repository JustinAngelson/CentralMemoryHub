"""
Shared database access for MCP tools.

Uses the same SQLAlchemy models and database as the Flask app.
This bypasses HTTP and gives MCP tools direct DB access.

IMPORTANT: The import paths below assume the standard CMH project layout.
Adjust if models.py or pinecone_client.py are in different locations.
"""
import os
import sys
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session

# Ensure the CMH project root is on the import path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ── Database Setup ────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionLocal = scoped_session(sessionmaker(bind=engine))
    logging.info(f"MCP tools: Database connected")
else:
    engine = None
    SessionLocal = None
    logging.warning("MCP tools: DATABASE_URL not set — DB access unavailable")


def get_db_session():
    """
    Get a scoped database session.
    Caller is responsible for calling session.close() when done.
    """
    if SessionLocal is None:
        raise RuntimeError("Database not configured. Set DATABASE_URL environment variable.")
    return SessionLocal()


# ── Import Existing Models ────────────────────────────────────────────

try:
    from models import (
        ProjectDecision,
        UnstructuredData,
        SharedContext,
        AgentDirectory,
        AgentSession,
        GPTMessage,
        OrgState,
        AgentTask,
        DecisionLog,
        KnowledgeIndex,
        MemoryLink,
        Experiment,
        UserInsight,
    )
    logging.info("MCP tools: All models imported successfully")
except ImportError as e:
    logging.error(f"MCP tools: Failed to import models — {e}")
    logging.error("Check that models.py is in the project root and all model classes exist.")
    raise

# ── Import Pinecone Client ────────────────────────────────────────────

try:
    import pinecone_client as pc
    PINECONE_AVAILABLE = True
    logging.info("MCP tools: Pinecone client available")
except ImportError:
    pc = None  # type: ignore
    PINECONE_AVAILABLE = False
    logging.warning("MCP tools: pinecone_client not importable — vector search unavailable")

# ── Public API ────────────────────────────────────────────────────────

__all__ = [
    "get_db_session",
    "pc",
    "PINECONE_AVAILABLE",
    # Models
    "ProjectDecision",
    "UnstructuredData",
    "SharedContext",
    "AgentDirectory",
    "AgentSession",
    "GPTMessage",
    "OrgState",
    "AgentTask",
    "DecisionLog",
    "KnowledgeIndex",
    "MemoryLink",
    "Experiment",
    "UserInsight",
]
