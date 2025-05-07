import os
import logging
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
from functools import wraps
import uuid
import platform
import socket

from flask import request, jsonify, render_template, Blueprint, current_app, make_response, after_this_request
from app import app, db
import pinecone_client as pc
from validation import handle_custom_gpt_request
from models import (
    # Existing models
    ProjectDecision, UnstructuredData, SharedContext,
    # New models
    AgentDirectory, AgentSession, GPTMessage, OrgState, AgentTask, DecisionLog,
    KnowledgeIndex, MemoryLink, Experiment, UserInsight
)

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# CORS middleware for Custom GPT compatibility
def add_cors_headers(response):
    """Add CORS and security headers to make API more accessible to Custom GPTs"""
    # CORS headers
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-KEY, Authorization, Accept'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Max-Age'] = '3600'  # Cache preflight requests
    
    # Additional headers for security and caching
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    return response

# Global middleware to add CORS headers to all responses
@app.after_request
def after_request_func(response):
    return add_cors_headers(response)
# Import security models from dedicated module
from api_keys import ApiKey, ApiRequestLog

# Set up authentication - For backwards compatibility 
DEFAULT_API_KEY = os.environ.get("API_KEY")

# Set up request rate limiting
class RateLimiter:
    """Thread-safe rate limiter for API requests."""
    
    def __init__(self):
        self.request_counts = {}  # {key_id: {timestamp: count}}
        self.lock = threading.Lock()
    
    def is_rate_limited(self, key_id: str, limit: int) -> bool:
        """Check if the request should be rate limited.
        
        Args:
            key_id: API key ID
            limit: Maximum requests per minute
            
        Returns:
            bool: True if the request should be rate limited
        """
        with self.lock:
            now = datetime.now()
            minute_ago = now - timedelta(minutes=1)
            
            # Initialize if this is the first request for this key
            if key_id not in self.request_counts:
                self.request_counts[key_id] = {}
            
            # Remove counts older than 1 minute
            self.request_counts[key_id] = {
                ts: count for ts, count in self.request_counts[key_id].items()
                if ts >= minute_ago
            }
            
            # Get the total count for the past minute
            total_count = sum(self.request_counts[key_id].values())
            
            # Check if the limit is reached
            if total_count >= limit:
                return True
            
            # Increment the count
            timestamp = now.replace(second=0, microsecond=0)  # Round to minute
            if timestamp not in self.request_counts[key_id]:
                self.request_counts[key_id][timestamp] = 0
            self.request_counts[key_id][timestamp] += 1
            
            return False

# Create a rate limiter instance
rate_limiter = RateLimiter()

def require_api_key(f):
    """Decorator to require API key for API endpoints with rate limiting and logging."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Handle preflight OPTIONS requests by returning early
        if request.method == 'OPTIONS':
            return '', 200
        
        status_code = 200  # Default success status
        api_key_id = None
        log_data = True
        
        try:
            # Check if the API key is provided in the header
            provided_key = request.headers.get("X-API-KEY")
            
            if not provided_key:
                status_code = 401
                return jsonify({"error": "Unauthorized. Missing API key."}), status_code
            
            # Support the legacy API key for backward compatibility
            if provided_key == DEFAULT_API_KEY:
                # Using the default API key (legacy support)
                api_key_id = "default"
                rate_limit = 200  # Higher limit for the default key
            else:
                # Look up the key in the database
                api_key = db.session.query(ApiKey).filter_by(api_key=provided_key).first()
                
                if not api_key:
                    status_code = 401
                    return jsonify({"error": "Unauthorized. Invalid API key."}), status_code
                
                if not api_key.is_valid():
                    status_code = 401
                    return jsonify({"error": "Unauthorized. Expired or inactive API key."}), status_code
                
                # Key is valid, update usage metrics
                api_key_id = api_key.key_id
                rate_limit = api_key.rate_limit
                api_key.update_last_used()
            
            # Check rate limiting
            if rate_limiter.is_rate_limited(api_key_id, rate_limit):
                status_code = 429
                return jsonify({
                    "error": "Too Many Requests",
                    "message": f"Rate limit of {rate_limit} requests per minute exceeded."
                }), status_code
            
            # Execute the actual function
            response = f(*args, **kwargs)
            
            # Get the status code from the response
            if isinstance(response, tuple) and len(response) > 1:
                status_code = response[1]
            
            return response
            
        finally:
            # Log the request (only if we have a key ID)
            if api_key_id:
                try:
                    ApiRequestLog.log_request(
                        api_key_id=api_key_id,
                        request=request,
                        status_code=status_code,
                        include_data=log_data
                    )
                except Exception as e:
                    # Don't fail the request if logging fails
                    logging.error(f"Failed to log API request: {str(e)}")
    
    return decorated_function

# Add content security policy to responses
def add_security_headers(response):
    """Add security headers to the response."""
    # Content Security Policy
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://cdn.replit.com https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "object-src 'none'; "
        "media-src 'self'; "
        "frame-src 'none'; "
        "frame-ancestors 'none';"
    )
    # Other security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response

# Apply security headers to all responses
app.after_request(add_security_headers)

# Route for the home page
@app.route('/')
def index():
    """Render the home page"""
    return render_template('index.html')

# System Health endpoints for integration with OpenAI Custom GPTs
@app.route('/sys/health', methods=['GET', 'POST'])
def health_check():
    """Health check endpoint for OpenAI Custom GPT integration."""
    try:
        # Check database connection
        db_ok = True
        try:
            db.session.execute(db.select(db.text("1"))).scalar()
        except Exception as e:
            db_ok = False
            logging.error(f"Database health check failed: {e}")
        
        # Check Pinecone connection
        pinecone_ok = True
        try:
            pc.get_index_stats()
        except Exception as e:
            pinecone_ok = False
            logging.error(f"Pinecone health check failed: {e}")
            
        health_status = {
            "status": "healthy" if db_ok and pinecone_ok else "degraded",
            "time": datetime.utcnow().isoformat(),
            "components": {
                "database": "up" if db_ok else "down",
                "vector_db": "up" if pinecone_ok else "down",
                "api": "up"
            },
            "version": "1.0.0"
        }
        
        return jsonify(health_status), 200
    except Exception as e:
        logging.error(f"Health check failed with error: {e}")
        return jsonify({
            "status": "error",
            "message": "Health check failed",
            "time": datetime.utcnow().isoformat()
        }), 500

@app.route('/openapi.json')
def serve_openapi_schema():
    """Serve the OpenAPI schema for Custom GPT integration."""
    try:
        schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'openapi-schema-fixed.json')
        with open(schema_path, 'r') as f:
            schema = json.load(f)
            
        # Set CORS headers for the OpenAPI schema
        response = make_response(jsonify(schema))
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-KEY'
        
        return response
    except Exception as e:
        logging.error(f"Error serving OpenAPI schema: {e}")
        return jsonify({
            "error": "Internal server error",
            "message": "Failed to load OpenAPI schema"
        }), 500
        
@app.route('/sys/gpt-diagnostic')
def gpt_diagnostic():
    """Enhanced diagnostic endpoint specifically for Custom GPT troubleshooting."""
    try:
        # Get system information
        hostname = socket.gethostname()
        try:
            local_ip = socket.gethostbyname(hostname)
        except:
            local_ip = "Unable to determine"
            
        # Get network information
        external_ip = request.remote_addr
        
        # Get request information
        headers = {k: v for k, v in request.headers.items()}
        
        # Perform basic connectivity tests
        pinecone_ok = True
        try:
            pc.get_index_stats()
        except Exception as e:
            pinecone_ok = False
            logging.error(f"Pinecone health check failed: {e}")
        
        # Build response with detailed diagnostics
        diagnostic_info = {
            "status": "connected",
            "timestamp": datetime.utcnow().isoformat(),
            "request_info": {
                "method": request.method,
                "path": request.path,
                "remote_addr": external_ip,
                "user_agent": request.user_agent.string if request.user_agent else "Unknown",
                "headers": headers
            },
            "server_info": {
                "hostname": hostname,
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "local_ip": local_ip
            },
            "connectivity": {
                "pinecone_connection": "up" if pinecone_ok else "down",
                "cors_enabled": True,
                "api_version": "1.0.0"
            },
            "notes": [
                "If you can see this response, your Custom GPT can reach this API.",
                "Check the request headers to ensure the X-API-KEY header is being sent correctly.",
                "For persistent connectivity issues, consider using a different domain or a proxy service."
            ],
            "troubleshooting_steps": [
                "Verify the API base URL is correctly configured in the Custom GPT actions section",
                "Ensure your API key is valid and properly formatted in the Custom GPT",
                "Try using webhooks or a stable public domain if direct connections continue to fail"
            ]
        }
        
        return jsonify(diagnostic_info)
    except Exception as e:
        logging.error(f"Diagnostic endpoint error: {e}")
        return jsonify({
            "status": "error",
            "message": f"Diagnostic check failed: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }), 500

@app.route('/agents')
def agents_view():
    """Render the agents interface"""
    return render_template('agent_view.html')

@app.route('/api-keys')
def api_keys_view():
    """Render the API key management interface"""
    return render_template('api_keys.html')

# API Key management endpoints
@app.route('/api/keys', methods=['GET'])
def get_api_keys():
    """Get all API keys (without requiring API key for demo purposes)"""
    try:
        # Get all API keys
        keys = ApiKey.query.all()
        return jsonify([key.to_dict() for key in keys])
    except Exception as e:
        logging.error(f"Error getting API keys: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/keys', methods=['POST'])
def create_api_key():
    """Create a new API key"""
    try:
        data = request.json
        
        # Validate required fields
        if 'name' not in data:
            return jsonify({"error": "Missing required field: name"}), 400
        
        # Optional fields
        description = data.get('description')
        expires_in_days = data.get('expires_in_days')
        rate_limit = data.get('rate_limit', 100)
        
        # Create the API key
        api_key = ApiKey.create(
            name=data['name'],
            description=description,
            expires_in_days=expires_in_days,
            rate_limit=rate_limit
        )
        
        # Return the API key (including the actual key)
        # This is the only time the actual key will be returned
        return jsonify(api_key.to_dict(include_key=True)), 201
    
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating API key: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/keys/<key_id>', methods=['PUT'])
def update_api_key(key_id):
    """Update an API key"""
    try:
        data = request.json
        key = ApiKey.query.get(key_id)
        
        if not key:
            return jsonify({"error": "API key not found"}), 404
        
        # Update fields
        if 'name' in data:
            key.name = data['name']
        if 'description' in data:
            key.description = data['description']
        if 'rate_limit' in data:
            key.rate_limit = data['rate_limit']
        if 'is_active' in data:
            key.is_active = data['is_active']
        
        db.session.commit()
        return jsonify(key.to_dict()), 200
    
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating API key: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/keys/<key_id>/revoke', methods=['POST'])
def revoke_api_key(key_id):
    """Revoke an API key"""
    try:
        key = ApiKey.query.get(key_id)
        
        if not key:
            return jsonify({"error": "API key not found"}), 404
        
        key.revoke()
        return jsonify({"message": "API key revoked successfully"}), 200
    
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error revoking API key: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/logs', methods=['GET'])
def get_api_logs():
    """Get API request logs with filtering options"""
    try:
        # Get query parameters
        key_id = request.args.get('key_id')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        
        # Build query
        query = db.session.query(ApiRequestLog)
        
        # Apply filters
        if key_id:
            query = query.filter(ApiRequestLog.api_key_id == key_id)
        
        # Order by most recent first
        query = query.order_by(ApiRequestLog.timestamp.desc())
        
        # Apply pagination
        query = query.limit(limit).offset(offset)
        
        # Execute query
        logs = query.all()
        
        # Count total
        total = db.session.query(ApiRequestLog).count()
        
        return jsonify({
            "logs": [log.__dict__ for log in logs if hasattr(log, '__dict__')],
            "total": total,
            "limit": limit,
            "offset": offset
        }), 200
    
    except Exception as e:
        logging.error(f"Error getting API logs: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/agents/sessions', methods=['GET'])
def get_agent_sessions_for_ui():
    """Get agent sessions for UI (without API key for demo purposes)"""
    try:
        # Get active sessions only
        active_sessions = AgentSession.query.filter(AgentSession.ended_at.is_(None)).all()
        return jsonify([session.to_dict() for session in active_sessions])
    except Exception as e:
        logging.error(f"Error getting agent sessions: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/agents/messages/<session_id>', methods=['GET'])
def get_session_messages_for_ui(session_id):
    """Get messages for a session for UI (without API key for demo purposes)"""
    try:
        # Check if session exists
        session = AgentSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({"error": "Session not found"}), 404
            
        # Get messages for this session
        messages = GPTMessage.query.filter_by(session_id=session_id).order_by(GPTMessage.timestamp).all()
        return jsonify([message.to_dict() for message in messages])
    except Exception as e:
        logging.error(f"Error getting session messages: {e}")
        return jsonify({"error": str(e)}), 500

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

# Define the validation schema for unstructured memory requests
unstructured_memory_schema = {
    'content': {
        'type': 'string',
        'required': True,
        'min_length': 1,
        'max_length': 10000
    }
}

# API endpoints for unstructured memory
@app.route('/memory/unstructured', methods=['POST'])
@require_api_key
@handle_custom_gpt_request(validator_schema=unstructured_memory_schema)
def add_unstructured_memory():
    """
    Add a new unstructured memory entry.
    Enhanced with robust error handling and flexible request parsing for Custom GPT integration.
    """
    try:
        # Get the validated data (comes from the handle_custom_gpt_request decorator)
        data = request.validated_data
        
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

# Import the handler from the validation module
from validation import handle_custom_gpt_request

# Define the validation schema for search requests
search_schema = {
    'query': {
        'type': 'string',
        'required': True,
        'min_length': 1,
        'max_length': 1000
    }
}

# API endpoint for search
@app.route('/search', methods=['POST'])
@require_api_key
@handle_custom_gpt_request(validator_schema=search_schema)
def search_memory():
    """
    Search unstructured data using Pinecone's similarity search.
    Enhanced with robust error handling and flexible request parsing for Custom GPT integration.
    """
    try:
        # Get the validated data (comes from the handle_custom_gpt_request decorator)
        data = request.validated_data
        
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
        query = "Unknown"
        if 'data' in locals() and hasattr(data, 'get'):
            query = data.get('query', 'Unknown')
        
        # Get connection status
        try:
            connection_status = pc.check_connection()
        except Exception as conn_error:
            connection_status = {"error": str(conn_error)}
            
        return jsonify({
            "error": "Search operation failed",
            "message": str(e),
            "query": query,
            "debug_info": {
                "exception_type": type(e).__name__,
                "pinecone_status": connection_status
            }
        }), 500

# Define the validation schema for shared context requests
shared_context_schema = {
    'sender': {
        'type': 'string',
        'required': True,
        'min_length': 1,
        'max_length': 100
    },
    'recipients': {
        'type': 'list',
        'required': True,
        'min_length': 1
    },
    'context_tag': {
        'type': 'string',
        'required': True,
        'min_length': 1,
        'max_length': 100
    },
    'memory_refs': {
        'type': 'list',
        'required': True,
        'min_length': 1
    }
}

# API endpoints for shared contexts
@app.route('/context', methods=['POST'])
@require_api_key
@handle_custom_gpt_request(validator_schema=shared_context_schema)
def add_shared_context():
    """Add a new shared context entry with enhanced validation for Custom GPT integration"""
    try:
        # Get the validated data (comes from the handle_custom_gpt_request decorator)
        data = request.validated_data
        
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
        
        # Get connection status for diagnostics
        try:
            connection_status = pc.check_connection()
        except Exception as conn_error:
            connection_status = {"error": str(conn_error)}
        
        return jsonify({
            "error": "Failed to add shared context",
            "message": str(e),
            "debug_info": {
                "exception_type": type(e).__name__,
                "service_status": connection_status
            }
        }), 500

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

# New API endpoints for multi-agent support

# Agent Directory (AI Org Chart) endpoints
@app.route('/api/directory', methods=['GET'])
def get_agent_directory_for_ui():
    """Get agent directory for UI (without API key for demo purposes)"""
    try:
        agents = AgentDirectory.query.all()
        return jsonify([agent.to_dict() for agent in agents])
    except Exception as e:
        logging.error(f"Error getting agent directory: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/directory/hierarchy', methods=['GET'])
def get_agent_hierarchy_for_ui():
    """Get agent hierarchy for UI (without API key for demo purposes)"""
    try:
        # Get all agents
        agents = AgentDirectory.query.all()
        
        # Build hierarchy map
        agent_map = {agent.agent_id: agent for agent in agents}
        hierarchy = []
        
        # Find root agents (those with no reports_to)
        for agent in agents:
            if agent.reports_to is None:
                # Create hierarchy starting with this root
                hierarchy.append(build_hierarchy_tree(agent, agent_map))
        
        return jsonify(hierarchy)
    except Exception as e:
        logging.error(f"Error getting agent hierarchy: {e}")
        return jsonify({"error": str(e)}), 500

# Define the validation schema for agent directory requests
agent_directory_schema = {
    'name': {
        'type': 'string',
        'required': True,
        'min_length': 2,
        'max_length': 100
    },
    'role': {
        'type': 'string',
        'required': True,
        'min_length': 2,
        'max_length': 100
    },
    'description': {
        'type': 'string',
        'required': False
    },
    'capabilities': {
        'type': 'list',
        'required': False
    },
    'reports_to': {
        'type': 'string',
        'required': False
    },
    'seniority_level': {
        'type': 'integer',
        'required': False,
        'min': 1,
        'max': 10
    },
    'status': {
        'type': 'string',
        'required': False,
        'allowed': ['active', 'inactive', 'archived']
    }
}

@app.route('/agent/directory', methods=['POST'])
@require_api_key
@handle_custom_gpt_request(validator_schema=agent_directory_schema)
def create_agent():
    """Create a new agent in the directory"""
    try:
        # Get the validated data (comes from the handle_custom_gpt_request decorator)
        data = request.validated_data
        
        # Check if agent name is unique
        existing_agent = AgentDirectory.query.filter_by(name=data['name']).first()
        if existing_agent:
            return jsonify({"error": f"Agent with name '{data['name']}' already exists"}), 400
        
        # Create a new agent
        agent = AgentDirectory(
            agent_id=str(uuid.uuid4()),
            name=data['name'],
            role=data['role'],
            description=data.get('description'),
            capabilities=data.get('capabilities', []),
            reports_to=data.get('reports_to'),
            seniority_level=data.get('seniority_level', 1),
            status=data.get('status', 'active')
        )
        
        # Save to database
        db.session.add(agent)
        db.session.commit()
        
        return jsonify({
            "agent_id": agent.agent_id,
            "message": "Agent created successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating agent: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/directory/<agent_id>', methods=['GET'])
@require_api_key
def get_agent(agent_id):
    """Get an agent by ID"""
    try:
        agent = AgentDirectory.query.get(agent_id)
        
        if agent:
            return jsonify(agent.to_dict()), 200
        else:
            return jsonify({"error": "Agent not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving agent: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/directory/<agent_id>', methods=['PUT'])
@require_api_key
def update_agent(agent_id):
    """Update an existing agent"""
    try:
        agent = AgentDirectory.query.get(agent_id)
        
        if not agent:
            return jsonify({"error": "Agent not found"}), 404
        
        data = request.json
        
        # Update fields if provided
        if 'name' in data:
            # Check if name already exists for a different agent
            existing = AgentDirectory.query.filter_by(name=data['name']).first()
            if existing and existing.agent_id != agent_id:
                return jsonify({"error": f"Agent with name '{data['name']}' already exists"}), 400
            agent.name = data['name']
        
        if 'role' in data:
            agent.role = data['role']
        if 'description' in data:
            agent.description = data['description']
        if 'capabilities' in data:
            agent.capabilities = data['capabilities']
        if 'reports_to' in data:
            agent.reports_to = data['reports_to']
        if 'seniority_level' in data:
            agent.seniority_level = data['seniority_level']
        if 'status' in data:
            agent.status = data['status']
        
        # Save changes
        db.session.commit()
        
        return jsonify({
            "message": "Agent updated successfully",
            "agent": agent.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating agent: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/directory/<agent_id>', methods=['DELETE'])
@require_api_key
def delete_agent(agent_id):
    """Delete an agent"""
    try:
        agent = AgentDirectory.query.get(agent_id)
        
        if not agent:
            return jsonify({"error": "Agent not found"}), 404
        
        # Check if agent has subordinates
        if agent.subordinates and len(agent.subordinates) > 0:
            return jsonify({"error": "Cannot delete agent with subordinates. Reassign subordinates first."}), 400
        
        # Check if agent has active sessions
        active_sessions = AgentSession.query.filter_by(
            agent_id=agent_id, 
            ended_at=None
        ).count()
        
        if active_sessions > 0:
            return jsonify({"error": "Cannot delete agent with active sessions"}), 400
        
        # Delete the agent
        db.session.delete(agent)
        db.session.commit()
        
        return jsonify({
            "message": "Agent deleted successfully"
        }), 200
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error deleting agent: {e}")
        return jsonify({"error": str(e)}), 500

# Helper function to build agent hierarchy tree
def build_hierarchy_tree(agent, agent_map):
    """Build a hierarchical tree for an agent and its subordinates"""
    agent_dict = agent.to_dict()
    subordinates = []
    
    # Get direct subordinates
    for sub_id, sub_agent in agent_map.items():
        if sub_agent.reports_to == agent.agent_id:
            subordinates.append(build_hierarchy_tree(sub_agent, agent_map))
    
    if subordinates:
        agent_dict['subordinates'] = subordinates
    
    return agent_dict

# Define the validation schema for agent sessions
agent_session_schema = {
    'agent_id': {
        'type': 'string',
        'required': True,
        'min_length': 1
    },
    'user_id': {
        'type': 'string',
        'required': False,
    },
    'current_focus': {
        'type': 'string',
        'required': False
    },
    'summary_notes': {
        'type': 'string',
        'required': False
    },
    'active_context_tags': {
        'type': 'list',
        'required': False
    }
}

# Agent Sessions endpoints
@app.route('/agent/sessions', methods=['POST'])
@require_api_key
@handle_custom_gpt_request(validator_schema=agent_session_schema)
def create_agent_session():
    """Create a new agent session"""
    try:
        # Get the validated data (comes from the handle_custom_gpt_request decorator)
        data = request.validated_data
        
        # Verify agent exists
        agent = AgentDirectory.query.get(data['agent_id'])
        if not agent:
            return jsonify({"error": f"Agent with ID '{data['agent_id']}' does not exist"}), 400
        
        # Create a new agent session
        session = AgentSession(
            session_id=str(uuid.uuid4()),
            agent_id=data['agent_id'],
            user_id=data.get('user_id'),
            current_focus=data.get('current_focus'),
            summary_notes=data.get('summary_notes'),
            active_context_tags=data.get('active_context_tags', [])
        )
        
        # Save to database
        db.session.add(session)
        db.session.commit()
        
        return jsonify({
            "session_id": session.session_id,
            "message": "Agent session created successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating agent session: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/sessions/<session_id>', methods=['GET'])
@require_api_key
def get_agent_session(session_id):
    """Get an agent session by ID"""
    try:
        session = AgentSession.query.get(session_id)
        
        if session:
            return jsonify(session.to_dict()), 200
        else:
            return jsonify({"error": "Agent session not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving agent session: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/sessions/<session_id>/end', methods=['PUT'])
@require_api_key
def end_agent_session(session_id):
    """End an agent session by setting its end time"""
    try:
        session = AgentSession.query.get(session_id)
        
        if not session:
            return jsonify({"error": "Agent session not found"}), 404
        
        # Set the ended_at timestamp
        session.ended_at = datetime.utcnow()
        
        # Save changes
        db.session.commit()
        
        return jsonify({
            "session_id": session.session_id,
            "message": "Agent session ended successfully"
        }), 200
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error ending agent session: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/sessions', methods=['GET'])
@require_api_key
def get_agent_sessions():
    """Get all agent sessions with optional filtering"""
    try:
        # Get query parameters for filtering
        agent_id = request.args.get('agent_id')
        user_id = request.args.get('user_id')
        active_only = request.args.get('active_only', 'false').lower() == 'true'
        
        # Build the query
        query = AgentSession.query
        
        if agent_id:
            query = query.filter(AgentSession.agent_id == agent_id)
        
        if user_id:
            query = query.filter(AgentSession.user_id == user_id)
        
        if active_only:
            query = query.filter(AgentSession.ended_at == None)
        
        # Get the results
        sessions = query.all()
        
        return jsonify([session.to_dict() for session in sessions]), 200
    except Exception as e:
        logging.error(f"Error retrieving agent sessions: {e}")
        return jsonify({"error": str(e)}), 500

# Define the validation schema for GPT messages
gpt_message_schema = {
    'sender_agent': {
        'type': 'string',
        'required': True,
        'min_length': 1
    },
    'receiver_agent': {
        'type': 'string',
        'required': False
    },
    'message_type': {
        'type': 'string',
        'required': True,
        'allowed': ['system', 'user', 'assistant', 'function', 'tool', 'data']
    },
    'content': {
        'type': 'string',
        'required': True,
        'min_length': 1
    },
    'session_id': {
        'type': 'string',
        'required': True,
        'min_length': 1
    }
}

# GPT Messages endpoints
@app.route('/agent/messages', methods=['POST'])
@require_api_key
@handle_custom_gpt_request(validator_schema=gpt_message_schema)
def create_gpt_message():
    """Create a new GPT message with enhanced validation for Custom GPT integration"""
    try:
        # Get the validated data (comes from the handle_custom_gpt_request decorator)
        data = request.validated_data
        
        # Check if the session exists
        session = AgentSession.query.get(data['session_id'])
        if not session:
            return jsonify({"error": "Invalid session_id. Session does not exist."}), 400
        
        # Create a new message
        message = GPTMessage(
            message_id=str(uuid.uuid4()),
            sender_agent=data['sender_agent'],
            receiver_agent=data.get('receiver_agent'),
            message_type=data['message_type'],
            content=data['content'],
            session_id=data['session_id']
        )
        
        # Save to database
        db.session.add(message)
        db.session.commit()
        
        return jsonify({
            "message_id": message.message_id,
            "message": "GPT message created successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating GPT message: {e}")
        
        # Get connection status for diagnostics
        try:
            connection_status = pc.check_connection()
        except Exception as conn_error:
            connection_status = {"error": str(conn_error)}
        
        return jsonify({
            "error": "Failed to create GPT message",
            "message": str(e),
            "debug_info": {
                "exception_type": type(e).__name__,
                "service_status": connection_status,
                "timestamp": datetime.utcnow().isoformat()
            }
        }), 500

@app.route('/agent/messages/<message_id>', methods=['GET'])
@require_api_key
def get_gpt_message(message_id):
    """Get a GPT message by ID"""
    try:
        message = GPTMessage.query.get(message_id)
        
        if message:
            return jsonify(message.to_dict()), 200
        else:
            return jsonify({"error": "GPT message not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving GPT message: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/sessions/<session_id>/messages', methods=['GET'])
@require_api_key
def get_session_messages(session_id):
    """Get all messages in a session"""
    try:
        # Check if the session exists
        session = AgentSession.query.get(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404
        
        # Get all messages in the session ordered by timestamp
        messages = GPTMessage.query.filter(
            GPTMessage.session_id == session_id
        ).order_by(GPTMessage.timestamp).all()
        
        return jsonify([message.to_dict() for message in messages]), 200
    except Exception as e:
        logging.error(f"Error retrieving session messages: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/messages', methods=['GET'])
@require_api_key
def get_gpt_messages():
    """Get GPT messages with filtering options"""
    try:
        # Get query parameters for filtering
        sender_agent = request.args.get('sender_agent')
        receiver_agent = request.args.get('receiver_agent')
        message_type = request.args.get('message_type')
        session_id = request.args.get('session_id')
        
        # Build the query
        query = GPTMessage.query
        
        if sender_agent:
            query = query.filter(GPTMessage.sender_agent == sender_agent)
        
        if receiver_agent:
            query = query.filter(GPTMessage.receiver_agent == receiver_agent)
        
        if message_type:
            query = query.filter(GPTMessage.message_type == message_type)
        
        if session_id:
            query = query.filter(GPTMessage.session_id == session_id)
        
        # Order by timestamp
        query = query.order_by(GPTMessage.timestamp)
        
        # Get the results
        messages = query.all()
        
        return jsonify([message.to_dict() for message in messages]), 200
    except Exception as e:
        logging.error(f"Error retrieving GPT messages: {e}")
        return jsonify({"error": str(e)}), 500

# Organizational State endpoints
@app.route('/org/state', methods=['POST'])
@require_api_key
def create_org_state():
    """Create a new organizational state entry"""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['entity', 'type', 'status', 'owner_agent', 'last_updated_by']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Create a new org state entry
        org_state = OrgState(
            entity_id=str(uuid.uuid4()),
            entity=data['entity'],
            type=data['type'],
            status=data['status'],
            summary=data.get('summary'),
            owner_agent=data['owner_agent'],
            last_updated_by=data['last_updated_by'],
            important_dates=data.get('important_dates'),
            linked_docs=data.get('linked_docs')
        )
        
        # Save to database
        db.session.add(org_state)
        db.session.commit()
        
        return jsonify({
            "entity_id": org_state.entity_id,
            "message": "Organizational state entry created successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating organizational state entry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/org/state/<entity_id>', methods=['GET'])
@require_api_key
def get_org_state(entity_id):
    """Get an organizational state entry by ID"""
    try:
        org_state = OrgState.query.get(entity_id)
        
        if org_state:
            return jsonify(org_state.to_dict()), 200
        else:
            return jsonify({"error": "Organizational state entry not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving organizational state entry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/org/state/<entity_id>', methods=['PUT'])
@require_api_key
def update_org_state(entity_id):
    """Update an organizational state entry"""
    try:
        org_state = OrgState.query.get(entity_id)
        
        if not org_state:
            return jsonify({"error": "Organizational state entry not found"}), 404
        
        data = request.json
        
        # Update fields if provided
        if 'status' in data:
            org_state.status = data['status']
        
        if 'summary' in data:
            org_state.summary = data['summary']
        
        if 'owner_agent' in data:
            org_state.owner_agent = data['owner_agent']
        
        if 'last_updated_by' in data:
            org_state.last_updated_by = data['last_updated_by']
        
        if 'important_dates' in data:
            org_state.important_dates = data['important_dates']
        
        if 'linked_docs' in data:
            org_state.linked_docs = data['linked_docs']
        
        # Update the updated_at timestamp
        org_state.updated_at = datetime.utcnow()
        
        # Save changes
        db.session.commit()
        
        return jsonify({
            "entity_id": org_state.entity_id,
            "message": "Organizational state entry updated successfully"
        }), 200
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating organizational state entry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/org/state', methods=['GET'])
@require_api_key
def get_org_states():
    """Get organizational state entries with filtering options"""
    try:
        # Get query parameters for filtering
        entity_type = request.args.get('type')
        status = request.args.get('status')
        owner_agent = request.args.get('owner_agent')
        
        # Build the query
        query = OrgState.query
        
        if entity_type:
            query = query.filter(OrgState.type == entity_type)
        
        if status:
            query = query.filter(OrgState.status == status)
        
        if owner_agent:
            query = query.filter(OrgState.owner_agent == owner_agent)
        
        # Get the results
        states = query.all()
        
        return jsonify([state.to_dict() for state in states]), 200
    except Exception as e:
        logging.error(f"Error retrieving organizational state entries: {e}")
        return jsonify({"error": str(e)}), 500

# Define the validation schema for agent tasks
agent_task_schema = {
    'title': {
        'type': 'string',
        'required': True,
        'min_length': 1,
        'max_length': 200
    },
    'description': {
        'type': 'string',
        'required': False
    },
    'assigned_to_agent': {
        'type': 'string',
        'required': True,
        'min_length': 1
    },
    'created_by_agent': {
        'type': 'string',
        'required': True,
        'min_length': 1
    },
    'status': {
        'type': 'string',
        'required': True,
        'allowed': ['pending', 'in_progress', 'completed', 'cancelled', 'blocked']
    },
    'priority': {
        'type': 'string',
        'required': False,
        'allowed': ['low', 'medium', 'high', 'critical']
    },
    'linked_project': {
        'type': 'string',
        'required': False
    },
    'summary_notes': {
        'type': 'string',
        'required': False
    },
    'due_date': {
        'type': 'string',
        'required': False
    }
}

# Agent Tasks endpoints
@app.route('/agent/tasks', methods=['POST'])
@require_api_key
@handle_custom_gpt_request(validator_schema=agent_task_schema)
def create_agent_task():
    """Create a new agent task with enhanced validation for Custom GPT integration"""
    try:
        # Get the validated data (comes from the handle_custom_gpt_request decorator)
        data = request.validated_data
        
        # Create a new task
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            title=data['title'],
            description=data.get('description'),
            assigned_to_agent=data['assigned_to_agent'],
            created_by_agent=data['created_by_agent'],
            status=data['status'],
            priority=data.get('priority'),
            linked_project=data.get('linked_project'),
            summary_notes=data.get('summary_notes'),
            due_date=datetime.fromisoformat(data['due_date']) if 'due_date' in data else None
        )
        
        # Save to database
        db.session.add(task)
        db.session.commit()
        
        return jsonify({
            "task_id": task.task_id,
            "message": "Agent task created successfully"
        }), 201
    except ValueError as e:
        db.session.rollback()
        logging.error(f"Error parsing date in agent task: {e}")
        return jsonify({"error": "Invalid date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating agent task: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/tasks/<task_id>', methods=['GET'])
@require_api_key
def get_agent_task(task_id):
    """Get an agent task by ID"""
    try:
        task = AgentTask.query.get(task_id)
        
        if task:
            return jsonify(task.to_dict()), 200
        else:
            return jsonify({"error": "Agent task not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving agent task: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/tasks/<task_id>', methods=['PUT'])
@require_api_key
def update_agent_task(task_id):
    """Update an agent task"""
    try:
        task = AgentTask.query.get(task_id)
        
        if not task:
            return jsonify({"error": "Agent task not found"}), 404
        
        data = request.json
        
        # Update fields if provided
        if 'title' in data:
            task.title = data['title']
        
        if 'description' in data:
            task.description = data['description']
        
        if 'assigned_to_agent' in data:
            task.assigned_to_agent = data['assigned_to_agent']
        
        if 'status' in data:
            task.status = data['status']
        
        if 'priority' in data:
            task.priority = data['priority']
        
        if 'linked_project' in data:
            task.linked_project = data['linked_project']
        
        if 'summary_notes' in data:
            task.summary_notes = data['summary_notes']
        
        if 'due_date' in data:
            task.due_date = datetime.fromisoformat(data['due_date']) if data['due_date'] else None
        
        # Update the updated_at timestamp
        task.updated_at = datetime.utcnow()
        
        # Save changes
        db.session.commit()
        
        return jsonify({
            "task_id": task.task_id,
            "message": "Agent task updated successfully"
        }), 200
    except ValueError as e:
        db.session.rollback()
        logging.error(f"Error parsing date in agent task update: {e}")
        return jsonify({"error": "Invalid date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating agent task: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/agent/tasks', methods=['GET'])
@require_api_key
def get_agent_tasks():
    """Get agent tasks with filtering options"""
    try:
        # Get query parameters for filtering
        assigned_to = request.args.get('assigned_to_agent')
        created_by = request.args.get('created_by_agent')
        status = request.args.get('status')
        linked_project = request.args.get('linked_project')
        
        # Build the query
        query = AgentTask.query
        
        if assigned_to:
            query = query.filter(AgentTask.assigned_to_agent == assigned_to)
        
        if created_by:
            query = query.filter(AgentTask.created_by_agent == created_by)
        
        if status:
            query = query.filter(AgentTask.status == status)
        
        if linked_project:
            query = query.filter(AgentTask.linked_project == linked_project)
        
        # Order by priority (if exists) and due_date
        query = query.order_by(AgentTask.priority.desc().nullslast(), AgentTask.due_date.asc().nullslast())
        
        # Get the results
        tasks = query.all()
        
        return jsonify([task.to_dict() for task in tasks]), 200
    except Exception as e:
        logging.error(f"Error retrieving agent tasks: {e}")
        return jsonify({"error": str(e)}), 500

# Decision Log endpoints
@app.route('/decision-log', methods=['POST'])
@require_api_key
def create_decision():
    """Create a new decision log entry"""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['context', 'made_by_agent', 'decision_text']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Create a new decision log entry
        decision = DecisionLog(
            decision_id=str(uuid.uuid4()),
            context=data['context'],
            made_by_agent=data['made_by_agent'],
            decision_text=data['decision_text'],
            impact_area=data.get('impact_area'),
            reversal_possible=data.get('reversal_possible', True)
        )
        
        # Save to database
        db.session.add(decision)
        db.session.commit()
        
        return jsonify({
            "decision_id": decision.decision_id,
            "message": "Decision log entry created successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating decision log entry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/decision-log/<decision_id>', methods=['GET'])
@require_api_key
def get_decision(decision_id):
    """Get a decision log entry by ID"""
    try:
        decision = DecisionLog.query.get(decision_id)
        
        if decision:
            return jsonify(decision.to_dict()), 200
        else:
            return jsonify({"error": "Decision log entry not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving decision log entry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/decision-log', methods=['GET'])
@require_api_key
def get_decisions():
    """Get decision log entries with filtering options"""
    try:
        # Get query parameters for filtering
        made_by = request.args.get('made_by_agent')
        impact_area = request.args.get('impact_area')
        reversal_possible = request.args.get('reversal_possible')
        
        # Handle date range filtering
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')
        
        # Build the query
        query = DecisionLog.query
        
        if made_by:
            query = query.filter(DecisionLog.made_by_agent == made_by)
        
        if impact_area:
            query = query.filter(DecisionLog.impact_area == impact_area)
        
        if reversal_possible is not None:
            reversal_bool = reversal_possible.lower() == 'true'
            query = query.filter(DecisionLog.reversal_possible == reversal_bool)
        
        if from_date:
            try:
                from_datetime = datetime.fromisoformat(from_date)
                query = query.filter(DecisionLog.timestamp >= from_datetime)
            except ValueError:
                return jsonify({"error": "Invalid from_date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"}), 400
        
        if to_date:
            try:
                to_datetime = datetime.fromisoformat(to_date)
                query = query.filter(DecisionLog.timestamp <= to_datetime)
            except ValueError:
                return jsonify({"error": "Invalid to_date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"}), 400
        
        # Order by timestamp (newest first)
        query = query.order_by(DecisionLog.timestamp.desc())
        
        # Get the results
        decisions = query.all()
        
        return jsonify([decision.to_dict() for decision in decisions]), 200
    except Exception as e:
        logging.error(f"Error retrieving decision log entries: {e}")
        return jsonify({"error": str(e)}), 500

# Knowledge Index endpoints
@app.route('/knowledge', methods=['POST'])
@require_api_key
def create_knowledge_entry():
    """Create a new knowledge index entry"""
    try:
        data = request.json
        
        # Validate required fields
        if 'term' not in data:
            return jsonify({"error": "Missing required field: term"}), 400
        
        # Create a new knowledge index entry
        knowledge = KnowledgeIndex(
            index_id=str(uuid.uuid4()),
            term=data['term'],
            defined_by_file=data.get('defined_by_file'),
            used_by_agents=data.get('used_by_agents'),
            relevance_score=data.get('relevance_score'),
            last_verified=datetime.fromisoformat(data['last_verified']) if 'last_verified' in data else None,
            synonyms=data.get('synonyms')
        )
        
        # Save to database
        db.session.add(knowledge)
        db.session.commit()
        
        return jsonify({
            "index_id": knowledge.index_id,
            "message": "Knowledge index entry created successfully"
        }), 201
    except ValueError as e:
        db.session.rollback()
        logging.error(f"Error parsing date in knowledge index: {e}")
        return jsonify({"error": "Invalid date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating knowledge index entry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/knowledge/<index_id>', methods=['GET'])
@require_api_key
def get_knowledge_entry(index_id):
    """Get a knowledge index entry by ID"""
    try:
        knowledge = KnowledgeIndex.query.get(index_id)
        
        if knowledge:
            return jsonify(knowledge.to_dict()), 200
        else:
            return jsonify({"error": "Knowledge index entry not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving knowledge index entry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/knowledge/<index_id>', methods=['PUT'])
@require_api_key
def update_knowledge_entry(index_id):
    """Update a knowledge index entry"""
    try:
        knowledge = KnowledgeIndex.query.get(index_id)
        
        if not knowledge:
            return jsonify({"error": "Knowledge index entry not found"}), 404
        
        data = request.json
        
        # Update fields if provided
        if 'term' in data:
            knowledge.term = data['term']
        
        if 'defined_by_file' in data:
            knowledge.defined_by_file = data['defined_by_file']
        
        if 'used_by_agents' in data:
            knowledge.used_by_agents = data['used_by_agents']
        
        if 'relevance_score' in data:
            knowledge.relevance_score = data['relevance_score']
        
        if 'last_verified' in data:
            knowledge.last_verified = datetime.fromisoformat(data['last_verified']) if data['last_verified'] else None
        
        if 'synonyms' in data:
            knowledge.synonyms = data['synonyms']
        
        # Update the updated_at timestamp
        knowledge.updated_at = datetime.utcnow()
        
        # Save changes
        db.session.commit()
        
        return jsonify({
            "index_id": knowledge.index_id,
            "message": "Knowledge index entry updated successfully"
        }), 200
    except ValueError as e:
        db.session.rollback()
        logging.error(f"Error parsing date in knowledge index update: {e}")
        return jsonify({"error": "Invalid date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating knowledge index entry: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/knowledge', methods=['GET'])
@require_api_key
def get_knowledge_entries():
    """Get knowledge index entries with filtering options"""
    try:
        # Get query parameters for filtering
        term = request.args.get('term')
        agent = request.args.get('agent')  # For filtering on used_by_agents
        min_relevance = request.args.get('min_relevance')
        
        # Build the query
        query = KnowledgeIndex.query
        
        if term:
            query = query.filter(KnowledgeIndex.term.ilike(f"%{term}%"))
        
        if agent:
            # Filter on JSONB array containing the agent
            query = query.filter(KnowledgeIndex.used_by_agents.cast(String).ilike(f"%{agent}%"))
        
        if min_relevance:
            try:
                min_rel_int = int(min_relevance)
                query = query.filter(KnowledgeIndex.relevance_score >= min_rel_int)
            except ValueError:
                return jsonify({"error": "min_relevance must be an integer"}), 400
        
        # Order by relevance_score desc, term asc
        query = query.order_by(KnowledgeIndex.relevance_score.desc().nullslast(), KnowledgeIndex.term.asc())
        
        # Get the results
        entries = query.all()
        
        return jsonify([entry.to_dict() for entry in entries]), 200
    except Exception as e:
        logging.error(f"Error retrieving knowledge index entries: {e}")
        return jsonify({"error": str(e)}), 500

# Memory Links endpoints
@app.route('/memory-links', methods=['POST'])
@require_api_key
def create_memory_link():
    """Create a new memory link"""
    try:
        data = request.json
        
        # Validate required fields
        if 'pinecone_vector_id' not in data:
            return jsonify({"error": "Missing required field: pinecone_vector_id"}), 400
        
        # Check if the pinecone_id exists in unstructured_data
        unstructured = UnstructuredData.query.filter_by(pinecone_id=data['pinecone_vector_id']).first()
        if not unstructured:
            return jsonify({"error": "Invalid pinecone_vector_id. No matching unstructured data found."}), 400
        
        # Create a new memory link
        memory_link = MemoryLink(
            link_id=str(uuid.uuid4()),
            pinecone_vector_id=data['pinecone_vector_id'],
            summary=data.get('summary'),
            linked_agent_event=data.get('linked_agent_event'),
            origin_file_or_source=data.get('origin_file_or_source')
        )
        
        # Save to database
        db.session.add(memory_link)
        db.session.commit()
        
        return jsonify({
            "link_id": memory_link.link_id,
            "message": "Memory link created successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating memory link: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/memory-links/<link_id>', methods=['GET'])
@require_api_key
def get_memory_link(link_id):
    """Get a memory link by ID"""
    try:
        memory_link = MemoryLink.query.get(link_id)
        
        if memory_link:
            return jsonify(memory_link.to_dict()), 200
        else:
            return jsonify({"error": "Memory link not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving memory link: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/memory-links', methods=['GET'])
@require_api_key
def get_memory_links():
    """Get memory links with filtering options"""
    try:
        # Get query parameters for filtering
        pinecone_id = request.args.get('pinecone_vector_id')
        linked_event = request.args.get('linked_agent_event')
        origin = request.args.get('origin_file_or_source')
        
        # Build the query
        query = MemoryLink.query
        
        if pinecone_id:
            query = query.filter(MemoryLink.pinecone_vector_id == pinecone_id)
        
        if linked_event:
            query = query.filter(MemoryLink.linked_agent_event == linked_event)
        
        if origin:
            query = query.filter(MemoryLink.origin_file_or_source.ilike(f"%{origin}%"))
        
        # Order by timestamp_added desc
        query = query.order_by(MemoryLink.timestamp_added.desc())
        
        # Get the results
        links = query.all()
        
        # Get the content for each link
        results = []
        for link in links:
            link_dict = link.to_dict()
            # Add the content from unstructured_data
            unstructured = UnstructuredData.query.filter_by(pinecone_id=link.pinecone_vector_id).first()
            if unstructured:
                link_dict['content'] = unstructured.content
            results.append(link_dict)
        
        return jsonify(results), 200
    except Exception as e:
        logging.error(f"Error retrieving memory links: {e}")
        return jsonify({"error": str(e)}), 500

# Experiments endpoints
@app.route('/experiments', methods=['POST'])
@require_api_key
def create_experiment():
    """Create a new experiment"""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['title', 'hypothesis', 'executing_agent', 'status']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Create a new experiment
        experiment = Experiment(
            experiment_id=str(uuid.uuid4()),
            title=data['title'],
            description=data.get('description'),
            hypothesis=data['hypothesis'],
            executing_agent=data['executing_agent'],
            outcome=data.get('outcome'),
            notes=data.get('notes'),
            status=data['status']
        )
        
        # Save to database
        db.session.add(experiment)
        db.session.commit()
        
        return jsonify({
            "experiment_id": experiment.experiment_id,
            "message": "Experiment created successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating experiment: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/experiments/<experiment_id>', methods=['GET'])
@require_api_key
def get_experiment(experiment_id):
    """Get an experiment by ID"""
    try:
        experiment = Experiment.query.get(experiment_id)
        
        if experiment:
            return jsonify(experiment.to_dict()), 200
        else:
            return jsonify({"error": "Experiment not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving experiment: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/experiments/<experiment_id>', methods=['PUT'])
@require_api_key
def update_experiment(experiment_id):
    """Update an experiment"""
    try:
        experiment = Experiment.query.get(experiment_id)
        
        if not experiment:
            return jsonify({"error": "Experiment not found"}), 404
        
        data = request.json
        
        # Update fields if provided
        if 'title' in data:
            experiment.title = data['title']
        
        if 'description' in data:
            experiment.description = data['description']
        
        if 'hypothesis' in data:
            experiment.hypothesis = data['hypothesis']
        
        if 'executing_agent' in data:
            experiment.executing_agent = data['executing_agent']
        
        if 'outcome' in data:
            experiment.outcome = data['outcome']
        
        if 'notes' in data:
            experiment.notes = data['notes']
        
        if 'status' in data:
            experiment.status = data['status']
        
        # Update the updated_at timestamp
        experiment.updated_at = datetime.utcnow()
        
        # Save changes
        db.session.commit()
        
        return jsonify({
            "experiment_id": experiment.experiment_id,
            "message": "Experiment updated successfully"
        }), 200
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating experiment: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/experiments', methods=['GET'])
@require_api_key
def get_experiments():
    """Get experiments with filtering options"""
    try:
        # Get query parameters for filtering
        status = request.args.get('status')
        agent = request.args.get('executing_agent')
        
        # Build the query
        query = Experiment.query
        
        if status:
            query = query.filter(Experiment.status == status)
        
        if agent:
            query = query.filter(Experiment.executing_agent == agent)
        
        # Order by created_at desc
        query = query.order_by(Experiment.created_at.desc())
        
        # Get the results
        experiments = query.all()
        
        return jsonify([experiment.to_dict() for experiment in experiments]), 200
    except Exception as e:
        logging.error(f"Error retrieving experiments: {e}")
        return jsonify({"error": str(e)}), 500

# User Insights endpoints
@app.route('/user-insights', methods=['POST'])
@require_api_key
def create_user_insight():
    """Create a new user insight"""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['user_id', 'interaction_type', 'summary']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Create a new user insight
        insight = UserInsight(
            insight_id=str(uuid.uuid4()),
            user_id=data['user_id'],
            interaction_type=data['interaction_type'],
            summary=data['summary'],
            related_agent_or_project=data.get('related_agent_or_project'),
            result=data.get('result'),
            tone_tag=data.get('tone_tag')
        )
        
        # Save to database
        db.session.add(insight)
        db.session.commit()
        
        return jsonify({
            "insight_id": insight.insight_id,
            "message": "User insight created successfully"
        }), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating user insight: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/user-insights/<insight_id>', methods=['GET'])
@require_api_key
def get_user_insight(insight_id):
    """Get a user insight by ID"""
    try:
        insight = UserInsight.query.get(insight_id)
        
        if insight:
            return jsonify(insight.to_dict()), 200
        else:
            return jsonify({"error": "User insight not found"}), 404
    except Exception as e:
        logging.error(f"Error retrieving user insight: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/user-insights', methods=['GET'])
@require_api_key
def get_user_insights():
    """Get user insights with filtering options"""
    try:
        # Get query parameters for filtering
        user_id = request.args.get('user_id')
        interaction_type = request.args.get('interaction_type')
        related_entity = request.args.get('related_agent_or_project')
        tone_tag = request.args.get('tone_tag')
        
        # Handle date range filtering
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')
        
        # Build the query
        query = UserInsight.query
        
        if user_id:
            query = query.filter(UserInsight.user_id == user_id)
        
        if interaction_type:
            query = query.filter(UserInsight.interaction_type == interaction_type)
        
        if related_entity:
            query = query.filter(UserInsight.related_agent_or_project == related_entity)
        
        if tone_tag:
            query = query.filter(UserInsight.tone_tag == tone_tag)
        
        if from_date:
            try:
                from_datetime = datetime.fromisoformat(from_date)
                query = query.filter(UserInsight.timestamp >= from_datetime)
            except ValueError:
                return jsonify({"error": "Invalid from_date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"}), 400
        
        if to_date:
            try:
                to_datetime = datetime.fromisoformat(to_date)
                query = query.filter(UserInsight.timestamp <= to_datetime)
            except ValueError:
                return jsonify({"error": "Invalid to_date format. Use ISO format (YYYY-MM-DDTHH:MM:SS)"}), 400
        
        # Order by timestamp desc
        query = query.order_by(UserInsight.timestamp.desc())
        
        # Get the results
        insights = query.all()
        
        return jsonify([insight.to_dict() for insight in insights]), 200
    except Exception as e:
        logging.error(f"Error retrieving user insights: {e}")
        return jsonify({"error": str(e)}), 500
