"""
Shared database access for MCP tools.

Uses the same SQLAlchemy models and database as the Flask app.
This bypasses HTTP and gives MCP tools direct DB access.
"""
import os
import sys
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionLocal = scoped_session(sessionmaker(bind=engine))
    logging.info("MCP tools: Database connected")
else:
    engine = None
    SessionLocal = None
    logging.warning("MCP tools: DATABASE_URL not set — DB access unavailable")


def get_db_session():
    """Get a scoped database session. Caller must call session.close() when done."""
    if SessionLocal is None:
        raise RuntimeError("Database not configured. Set DATABASE_URL environment variable.")
    return SessionLocal()


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
    raise

try:
    import pinecone_client as pc
    PINECONE_AVAILABLE = True
    logging.info("MCP tools: Pinecone client available")
except ImportError:
    pc = None
    PINECONE_AVAILABLE = False
    logging.warning("MCP tools: pinecone_client not importable — vector search unavailable")

__all__ = [
    "get_db_session",
    "pc",
    "PINECONE_AVAILABLE",
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
