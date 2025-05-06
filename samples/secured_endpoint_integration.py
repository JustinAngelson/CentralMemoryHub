"""
Example of integrating the secure API components with existing endpoints.
This demonstrates how to migrate from the current API implementation to the enhanced secure version.
"""
from flask import request, jsonify
from app import app, db
import uuid
import pinecone_client as pc
from models import UnstructuredData

# Import security components
from validation import ValidationError, validate_request_data
from xss_protection import sanitize_recursive, sanitize_html
from secure_api import secure_endpoint
import csrf

# Example: Converting an existing endpoint to use the secure_endpoint decorator
# Original implementation:
"""
@app.route('/memory/unstructured', methods=['POST'])
@require_api_key
def add_unstructured_memory():
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
"""

# Enhanced implementation with secure_endpoint decorator
# This demonstrates how to use the validation schema and enhanced security

# Define the validation schema for unstructured memory
unstructured_memory_schema = {
    'content': {
        'type': 'string',
        'required': True,
        'min_length': 1,
        'max_length': 100000  # Set an appropriate maximum length
    },
    'tags': {
        'type': 'list',
        'required': False,
        'item_validator': lambda x, f: validate_request_data(x, {'name': {'type': 'string', 'required': True}}),
        'max_length': 10
    },
    'metadata': {
        'type': 'dict',
        'required': False,
        'key_validators': {
            'source': lambda x, f: x if isinstance(x, str) else str(x),
            'priority': lambda x, f: int(x) if 1 <= int(x) <= 5 else 3
        }
    }
}

"""
@app.route('/memory/unstructured/secure', methods=['POST'])
@secure_endpoint(
    validator_schema=unstructured_memory_schema,
    require_api_key=True,
    sanitize_input=True,
    rate_limit=20,  # Override default rate limit for this endpoint
    log_request=True
)
def add_unstructured_memory_secure():
    # The data has already been validated and sanitized by the decorator
    # You can access it using request.validated_data
    data = request.validated_data
    
    try:
        # Process the content with Pinecone
        embedding, pinecone_id = pc.process_unstructured_data(data['content'])
        
        # Create a new unstructured data entry
        unstructured_data = UnstructuredData(
            id=str(uuid.uuid4()),
            content=data['content'],
            pinecone_id=pinecone_id
        )
        
        # Add tags and metadata if provided
        if 'tags' in data:
            unstructured_data.tags = data['tags']
            
        if 'metadata' in data:
            unstructured_data.metadata = data['metadata']
        
        # Save to database
        db.session.add(unstructured_data)
        db.session.commit()
        
        return {
            "id": unstructured_data.id,
            "pinecone_id": pinecone_id,
            "message": "Unstructured memory added successfully"
        }, 201
        
    except Exception as e:
        db.session.rollback()
        # We don't need to handle logging here as the decorator does it
        # We also don't need to format the response as the decorator does it
        raise
"""

# Example: Converting search endpoint to use the secure API wrapper
search_schema = {
    'query': {
        'type': 'string',
        'required': True,
        'min_length': 1,
        'max_length': 1000
    },
    'limit': {
        'type': 'integer',
        'required': False,
        'min_value': 1,
        'max_value': 100
    },
    'filters': {
        'type': 'dict',
        'required': False
    }
}

"""
@app.route('/search/secure', methods=['POST'])
@secure_endpoint(
    validator_schema=search_schema,
    require_api_key=True,
    sanitize_input=True
)
def search_memory_secure():
    data = request.validated_data
    
    try:
        # Extract parameters
        query = data['query']
        limit = data.get('limit', 10)  # Default to 10 results
        filters = data.get('filters', {})
        
        # Perform search with Pinecone
        pinecone_results = pc.search_by_content(query, limit=limit, filters=filters)
        
        # Get the matching Pinecone IDs
        pinecone_ids = [match['id'] for match in pinecone_results]
        
        # Get the corresponding unstructured data entries
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
        
        return {
            "query": query,
            "results": results
        }, 200
        
    except Exception as e:
        # The decorator will handle error responses
        raise
"""

# Example: Using CSRF protection with a form-based endpoint
"""
@app.route('/admin/settings', methods=['GET'])
def get_settings_form():
    # Generate a CSRF token for the form
    csrf_token = csrf.generate_csrf_token()
    
    # Get current settings (just an example)
    settings = {
        'site_name': 'Central Memory Hub',
        'max_results': 20,
        'enable_public_api': False
    }
    
    return render_template(
        'admin/settings.html',
        csrf_token=csrf_token,
        settings=settings
    )

@app.route('/admin/settings', methods=['POST'])
@csrf.csrf_protect
def update_settings():
    # The CSRF token has been validated by the decorator
    
    try:
        # Validate and sanitize input
        site_name = request.form.get('site_name', '')
        site_name = sanitize_html(site_name)
        
        max_results = request.form.get('max_results', '20')
        try:
            max_results = int(max_results)
            if max_results < 1 or max_results > 100:
                max_results = 20
        except ValueError:
            max_results = 20
            
        enable_public_api = request.form.get('enable_public_api') == 'on'
        
        # Update settings (example implementation)
        # settings.site_name = site_name
        # settings.max_results = max_results
        # settings.enable_public_api = enable_public_api
        # db.session.commit()
        
        # Redirect with success message
        return redirect(url_for('get_settings_form', message='Settings updated successfully'))
        
    except Exception as e:
        # Log the error and redirect with error message
        return redirect(url_for('get_settings_form', error=str(e)))
"""

# Example: Using secure_endpoint with a GET endpoint that includes pagination
pagination_schema = {
    'page': {
        'type': 'integer',
        'required': False,
        'min_value': 1
    },
    'per_page': {
        'type': 'integer',
        'required': False,
        'min_value': 1,
        'max_value': 100
    },
    'sort_by': {
        'type': 'string',
        'required': False
    },
    'sort_order': {
        'type': 'string',
        'required': False
    }
}

"""
@app.route('/api/memories', methods=['GET'])
@secure_endpoint(
    validator_schema=pagination_schema,
    require_api_key=True
)
def get_memories():
    # Get validated query parameters
    data = request.validated_data
    
    # Extract parameters with defaults
    page = data.get('page', 1)
    per_page = data.get('per_page', 20)
    sort_by = data.get('sort_by', 'timestamp')
    sort_order = data.get('sort_order', 'desc')
    
    # Calculate offset
    offset = (page - 1) * per_page
    
    try:
        # Build query
        query = db.session.query(UnstructuredData)
        
        # Apply sorting
        if sort_order.lower() == 'desc':
            query = query.order_by(getattr(UnstructuredData, sort_by).desc())
        else:
            query = query.order_by(getattr(UnstructuredData, sort_by).asc())
        
        # Apply pagination
        query = query.limit(per_page).offset(offset)
        
        # Execute query
        memories = query.all()
        
        # Count total
        total = db.session.query(UnstructuredData).count()
        
        # Calculate pagination metadata
        total_pages = (total + per_page - 1) // per_page
        has_next = page < total_pages
        has_prev = page > 1
        
        return {
            "memories": [memory.to_dict() for memory in memories],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "has_next": has_next,
                "has_prev": has_prev
            }
        }, 200
        
    except Exception as e:
        raise
"""