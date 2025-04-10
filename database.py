import os
import sqlite3
import json
import logging
from typing import Dict, List, Any, Optional, Union

# Database path
DB_PATH = 'memory_hub.db'

def dict_factory(cursor, row):
    """Convert row factory to dictionary"""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

def get_db_connection():
    """Create a database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    return conn

def init_db():
    """Initialize the database with required tables"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create project_decisions table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS project_decisions (
        id TEXT PRIMARY KEY,
        gpt_role TEXT,
        decision_text TEXT,
        context_embedding TEXT,
        related_documents TEXT,
        timestamp TEXT
    )
    ''')

    # Create unstructured_data table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS unstructured_data (
        id TEXT PRIMARY KEY,
        content TEXT,
        pinecone_id TEXT
    )
    ''')

    # Create shared_contexts table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shared_contexts (
        id TEXT PRIMARY KEY,
        sender TEXT,
        recipients TEXT,
        context_tag TEXT,
        memory_refs TEXT,
        timestamp TEXT
    )
    ''')

    conn.commit()
    conn.close()
    logging.info("Database initialized successfully")

# Functions for project_decisions table
def add_project_decision(
    id: str, 
    gpt_role: str, 
    decision_text: str, 
    context_embedding: List[float], 
    related_documents: List[str], 
    timestamp: str
) -> bool:
    """Add a new project decision to the database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Serialize lists and vectors to JSON
        serialized_embedding = json.dumps(context_embedding)
        serialized_docs = json.dumps(related_documents)
        
        cursor.execute('''
        INSERT INTO project_decisions (id, gpt_role, decision_text, context_embedding, related_documents, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (id, gpt_role, decision_text, serialized_embedding, serialized_docs, timestamp))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error adding project decision: {e}")
        return False

def get_project_decision(id: str) -> Optional[Dict[str, Any]]:
    """Get a project decision by ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM project_decisions WHERE id = ?', (id,))
        decision = cursor.fetchone()
        
        if decision:
            # Deserialize JSON strings back to Python objects
            decision['context_embedding'] = json.loads(decision['context_embedding'])
            decision['related_documents'] = json.loads(decision['related_documents'])
        
        conn.close()
        return decision
    except Exception as e:
        logging.error(f"Error retrieving project decision: {e}")
        return None

# Functions for unstructured_data table
def add_unstructured_data(id: str, content: str, pinecone_id: str) -> bool:
    """Add unstructured data to the database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO unstructured_data (id, content, pinecone_id)
        VALUES (?, ?, ?)
        ''', (id, content, pinecone_id))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error adding unstructured data: {e}")
        return False

def get_unstructured_data(id: str) -> Optional[Dict[str, Any]]:
    """Get unstructured data by ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM unstructured_data WHERE id = ?', (id,))
        data = cursor.fetchone()
        
        conn.close()
        return data
    except Exception as e:
        logging.error(f"Error retrieving unstructured data: {e}")
        return None

def get_unstructured_data_by_pinecone_ids(pinecone_ids: List[str]) -> List[Dict[str, Any]]:
    """Get unstructured data by Pinecone IDs"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        placeholders = ','.join(['?'] * len(pinecone_ids))
        cursor.execute(f'SELECT * FROM unstructured_data WHERE pinecone_id IN ({placeholders})', pinecone_ids)
        data = cursor.fetchall()
        
        conn.close()
        return data
    except Exception as e:
        logging.error(f"Error retrieving unstructured data by Pinecone IDs: {e}")
        return []

# Functions for shared_contexts table
def add_shared_context(
    id: str, 
    sender: str, 
    recipients: List[str], 
    context_tag: str, 
    memory_refs: List[str], 
    timestamp: str
) -> bool:
    """Add a shared context to the database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Serialize lists to JSON
        serialized_recipients = json.dumps(recipients)
        serialized_memory_refs = json.dumps(memory_refs)
        
        cursor.execute('''
        INSERT INTO shared_contexts (id, sender, recipients, context_tag, memory_refs, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (id, sender, serialized_recipients, context_tag, serialized_memory_refs, timestamp))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"Error adding shared context: {e}")
        return False

def get_all_shared_contexts() -> List[Dict[str, Any]]:
    """Get all shared contexts"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM shared_contexts')
        contexts = cursor.fetchall()
        
        # Deserialize JSON strings back to Python objects for each context
        for context in contexts:
            context['recipients'] = json.loads(context['recipients'])
            context['memory_refs'] = json.loads(context['memory_refs'])
        
        conn.close()
        return contexts
    except Exception as e:
        logging.error(f"Error retrieving shared contexts: {e}")
        return []
