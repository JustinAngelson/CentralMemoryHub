import os
import logging
import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from functools import wraps
import uuid

from flask import request, jsonify, render_template, Blueprint, current_app
from app import app, db
import pinecone_client as pc
from models import ProjectDecision, UnstructuredData, SharedContext

# Set up authentication
API_KEY = os.environ.get("API_KEY")

def require_api_key(f):
    """Decorator to require API key for API endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Handle preflight OPTIONS requests by returning early
        if request.method == 'OPTIONS':
            return '', 200
            
        # Check if the API key is provided in the header
        provided_key = request.headers.get("X-API-KEY")
        if not provided_key or provided_key != API_KEY:
            return jsonify({"error": "Unauthorized. Invalid or missing API key."}), 401
        return f(*args, **kwargs)
    return decorated_function

# Route for the home page
@app.route('/')
def index():
    """Render the home page"""
    return render_template('index.html')

# API endpoints for structured memory
@app.route('/memory/structured', methods=['POST'])
@require_api_key
def add_structured_memory():
    """Add a new structured memory entry"""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['gpt_role', 'decision_text', 'context_embedding', 'related_documents']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Create a new project decision using SQLAlchemy model
        decision = ProjectDecision(
            id=str(uuid.uuid4()),
            gpt_role=data['gpt_role'],
            decision_text=data['decision_text'],
            context_embedding=data['context_embedding'],
            related_documents=data['related_documents']
        )
        
        # Save to database using SQLAlchemy
        db.session.add(decision)
        db.session.commit()
        
        return jsonify({
            "id": decision.id, 
            "message": "Structured memory added successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error adding structured memory: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/memory/structured/<id>', methods=['GET'])
@require_api_key
def get_structured_memory(id):
    """Get a structured memory entry by ID"""
    try:
        decision = ProjectDecision.query.get(id)
        
        if decision:
            return jsonify(decision.to_dict()), 200
        else:
            return jsonify({"error": "Structured memory not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving structured memory: {e}")
        return jsonify({"error": str(e)}), 500

# API endpoints for unstructured memory
@app.route('/memory/unstructured', methods=['POST'])
@require_api_key
def add_unstructured_memory():
    """Add a new unstructured memory entry"""
    try:
        data = request.json
        
        # Validate required fields
        if 'content' not in data:
            return jsonify({"error": "Missing required field: content"}), 400
        
        # Process the content with Pinecone
        embedding, pinecone_id = pc.process_unstructured_data(data['content'])
        
        # Create a new unstructured data entry using SQLAlchemy model
        unstructured_data = UnstructuredData(
            id=str(uuid.uuid4()),
            content=data['content'],
            pinecone_id=pinecone_id
        )
        
        # Save to database using SQLAlchemy
        db.session.add(unstructured_data)
        db.session.commit()
        
        return jsonify({
            "id": unstructured_data.id,
            "pinecone_id": pinecone_id,
            "message": "Unstructured memory added successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error adding unstructured memory: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/memory/unstructured/<id>', methods=['GET'])
@require_api_key
def get_unstructured_memory(id):
    """Get an unstructured memory entry by ID"""
    try:
        data = UnstructuredData.query.get(id)
        
        if data:
            return jsonify(data.to_dict()), 200
        else:
            return jsonify({"error": "Unstructured memory not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving unstructured memory: {e}")
        return jsonify({"error": str(e)}), 500

# API endpoint for search
@app.route('/search', methods=['POST'])
@require_api_key
def search_memory():
    """Search unstructured data using Pinecone's similarity search"""
    try:
        data = request.json
        
        # Validate required fields
        if 'query' not in data:
            return jsonify({"error": "Missing required field: query"}), 400
        
        # Perform search with Pinecone
        pinecone_results = pc.search_by_content(data['query'])
        
        # Get the matching Pinecone IDs
        pinecone_ids = [match['id'] for match in pinecone_results]
        
        # Get the corresponding unstructured data entries using SQLAlchemy
        memory_entries = UnstructuredData.query.filter(
            UnstructuredData.pinecone_id.in_(pinecone_ids)
        ).all()
        
        # Convert to dictionaries and add similarity scores
        results = []
        for entry in memory_entries:
            entry_dict = entry.to_dict()
            # Add similarity score from Pinecone results
            for match in pinecone_results:
                if entry.pinecone_id == match['id']:
                    entry_dict['similarity_score'] = match['score']
                    break
            results.append(entry_dict)
        
        # Sort by similarity score (highest first)
        results.sort(key=lambda x: x.get('similarity_score', 0), reverse=True)
        
        return jsonify({
            "query": data['query'],
            "results": results
        }), 200
    except Exception as e:
        logging.error(f"Error performing search: {e}")
        return jsonify({"error": str(e)}), 500

# API endpoints for shared contexts
@app.route('/context', methods=['POST'])
@require_api_key
def add_shared_context():
    """Add a new shared context entry"""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['sender', 'recipients', 'context_tag', 'memory_refs']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Create a new shared context using SQLAlchemy model
        context = SharedContext(
            id=str(uuid.uuid4()),
            sender=data['sender'],
            recipients=data['recipients'],
            context_tag=data['context_tag'],
            memory_refs=data['memory_refs']
        )
        
        # Save to database using SQLAlchemy
        db.session.add(context)
        db.session.commit()
        
        return jsonify({
            "id": context.id,
            "message": "Shared context added successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error adding shared context: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/context', methods=['GET'])
@require_api_key
def get_all_contexts():
    """Get all shared context entries"""
    try:
        contexts = SharedContext.query.all()
        return jsonify([context.to_dict() for context in contexts]), 200
    except Exception as e:
        logging.error(f"Error retrieving shared contexts: {e}")
        return jsonify({"error": str(e)}), 500
