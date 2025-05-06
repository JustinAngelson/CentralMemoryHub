import os
import logging
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from psycopg2 import sql
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

def get_pg_connection():
    """Connect to PostgreSQL with environment variables"""
    conn = psycopg2.connect(
        host=os.environ.get("PGHOST"),
        database=os.environ.get("PGDATABASE"),
        user=os.environ.get("PGUSER"),
        password=os.environ.get("PGPASSWORD"),
        port=os.environ.get("PGPORT")
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn

def upgrade_existing_tables():
    """Update existing tables to match the new model definitions"""
    try:
        conn = get_pg_connection()
        cursor = conn.cursor()
        
        logging.info("Checking if unstructured_data.pinecone_id needs a unique constraint...")
        
        # Check if the unique constraint already exists on pinecone_id
        cursor.execute("""
        SELECT COUNT(*) FROM pg_constraint 
        WHERE conrelid = 'unstructured_data'::regclass 
        AND conname LIKE '%pinecone_id%' 
        AND contype = 'u'
        """)
        constraint_exists = cursor.fetchone()[0] > 0
        
        if not constraint_exists:
            logging.info("Adding unique constraint to unstructured_data.pinecone_id...")
            # Add unique constraint to pinecone_id
            cursor.execute("""
            ALTER TABLE unstructured_data 
            ADD CONSTRAINT unstructured_data_pinecone_id_key UNIQUE (pinecone_id);
            """)
            logging.info("✓ Unique constraint added to pinecone_id")
            
            # Add index on pinecone_id if it doesn't exist
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_unstructured_data_pinecone_id ON unstructured_data (pinecone_id);
            """)
            logging.info("✓ Index added to pinecone_id")
        else:
            logging.info("✓ Unique constraint already exists on pinecone_id")
        
        cursor.close()
        conn.close()
        
        logging.info("Existing tables updated successfully")
    except Exception as e:
        logging.error(f"Error updating existing tables: {e}")
        raise

def create_new_tables():
    """Create all new tables defined in the models"""
    try:
        with app.app_context():
            logging.info("Creating new tables...")
            
            # Create all tables
            db.create_all()
            
            # Verify if new tables were created
            new_tables = [
                'agent_sessions', 'gpt_messages', 'org_state', 'agent_tasks',
                'decision_log', 'kb_index', 'memory_links', 'experiments', 'user_insights'
            ]
            
            engine = db.engine
            inspector = db.inspect(engine)
            existing_tables = inspector.get_table_names()
            
            for table in new_tables:
                if table in existing_tables:
                    logging.info(f"✓ Table {table} exists")
                else:
                    logging.error(f"✗ Table {table} not found")
            
            logging.info("New tables created successfully")
    except Exception as e:
        logging.error(f"Error creating new tables: {e}")
        raise

def run_migration():
    """Run the full database migration"""
    logging.info("Starting database migration...")
    
    # First update existing tables
    upgrade_existing_tables()
    
    # Then create new tables
    create_new_tables()
    
    logging.info("Database migration completed successfully")

if __name__ == "__main__":
    run_migration()