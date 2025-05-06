import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from app import app, db
from models import (
    # Existing models
    ProjectDecision, UnstructuredData, SharedContext,
    # New models
    AgentSession, GPTMessage, OrgState, AgentTask, DecisionLog,
    KnowledgeIndex, MemoryLink, Experiment, UserInsight
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()

def setup_database():
    """Create all tables defined in the models"""
    try:
        with app.app_context():
            logging.info("Starting database schema update...")
            
            # Create all tables if they don't exist
            db.create_all()
            
            logging.info("Database schema updated successfully.")
            
            # Check if tables were created
            all_tables = [
                'project_decisions', 'unstructured_data', 'shared_contexts',
                'agent_sessions', 'gpt_messages', 'org_state', 'agent_tasks', 
                'decision_log', 'kb_index', 'memory_links', 'experiments', 'user_insights'
            ]
            
            # This is a simple way to verify tables exist
            engine = db.engine
            inspector = db.inspect(engine)
            existing_tables = inspector.get_table_names()
            
            for table in all_tables:
                if table in existing_tables:
                    logging.info(f"✓ Table {table} exists")
                else:
                    logging.error(f"✗ Table {table} not found")
            
            logging.info("Database enhancement completed.")
    except Exception as e:
        logging.error(f"Error setting up database: {e}")
        raise

if __name__ == "__main__":
    setup_database()