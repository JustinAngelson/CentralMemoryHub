import os
import json
import sqlite3
import logging
from dotenv import load_dotenv
from datetime import datetime
from app import app, db
from models import ProjectDecision, UnstructuredData, SharedContext

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()

# SQLite database path
SQLITE_DB_PATH = 'memory_hub.db'

def dict_factory(cursor, row):
    """Convert SQLite row to dictionary"""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

def get_sqlite_connection():
    """Create a connection to the SQLite database"""
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = dict_factory
    return conn

def migrate_project_decisions():
    """Migrate project decisions from SQLite to PostgreSQL"""
    try:
        # Get data from SQLite
        sqlite_conn = get_sqlite_connection()
        cursor = sqlite_conn.cursor()
        cursor.execute('SELECT * FROM project_decisions')
        decisions = cursor.fetchall()
        sqlite_conn.close()
        
        logging.info(f"Found {len(decisions)} project decisions to migrate")
        
        # Insert into PostgreSQL
        with app.app_context():
            for decision in decisions:
                # Parse JSON strings from SQLite
                context_embedding = json.loads(decision['context_embedding'])
                related_documents = json.loads(decision['related_documents'])
                
                # Create PostgreSQL record
                new_decision = ProjectDecision(
                    id=decision['id'],
                    gpt_role=decision['gpt_role'],
                    decision_text=decision['decision_text'],
                    context_embedding=context_embedding,
                    related_documents=related_documents,
                    timestamp=datetime.fromisoformat(decision['timestamp'])
                )
                
                # Add to session
                db.session.add(new_decision)
            
            # Commit the transaction
            db.session.commit()
            logging.info("Successfully migrated project decisions")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error migrating project decisions: {e}")

def migrate_unstructured_data():
    """Migrate unstructured data from SQLite to PostgreSQL"""
    try:
        # Get data from SQLite
        sqlite_conn = get_sqlite_connection()
        cursor = sqlite_conn.cursor()
        cursor.execute('SELECT * FROM unstructured_data')
        data_entries = cursor.fetchall()
        sqlite_conn.close()
        
        logging.info(f"Found {len(data_entries)} unstructured data entries to migrate")
        
        # Insert into PostgreSQL
        with app.app_context():
            for entry in data_entries:
                # Create PostgreSQL record
                new_entry = UnstructuredData(
                    id=entry['id'],
                    content=entry['content'],
                    pinecone_id=entry['pinecone_id']
                )
                
                # Add to session
                db.session.add(new_entry)
            
            # Commit the transaction
            db.session.commit()
            logging.info("Successfully migrated unstructured data")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error migrating unstructured data: {e}")

def migrate_shared_contexts():
    """Migrate shared contexts from SQLite to PostgreSQL"""
    try:
        # Get data from SQLite
        sqlite_conn = get_sqlite_connection()
        cursor = sqlite_conn.cursor()
        cursor.execute('SELECT * FROM shared_contexts')
        contexts = cursor.fetchall()
        sqlite_conn.close()
        
        logging.info(f"Found {len(contexts)} shared contexts to migrate")
        
        # Insert into PostgreSQL
        with app.app_context():
            for context in contexts:
                # Parse JSON strings from SQLite
                recipients = json.loads(context['recipients'])
                memory_refs = json.loads(context['memory_refs'])
                
                # Create PostgreSQL record
                new_context = SharedContext(
                    id=context['id'],
                    sender=context['sender'],
                    recipients=recipients,
                    context_tag=context['context_tag'],
                    memory_refs=memory_refs,
                    timestamp=datetime.fromisoformat(context['timestamp'])
                )
                
                # Add to session
                db.session.add(new_context)
            
            # Commit the transaction
            db.session.commit()
            logging.info("Successfully migrated shared contexts")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error migrating shared contexts: {e}")

def run_migration():
    """Run the full migration process"""
    logging.info("Starting migration from SQLite to PostgreSQL")
    
    # Make sure the tables exist in PostgreSQL
    with app.app_context():
        db.create_all()
        logging.info("Verified PostgreSQL tables exist")
    
    # Migrate each table
    migrate_project_decisions()
    migrate_unstructured_data()
    migrate_shared_contexts()
    
    logging.info("Migration completed")

if __name__ == "__main__":
    run_migration()