import os
import logging
import json
from typing import List, Dict, Any, Optional, Tuple, Union
import uuid
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec

# Initialize the OpenAI client
# The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
# Do not change this unless explicitly requested by the user
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Initialize Pinecone client
pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))

# Pinecone index name
PINECONE_INDEX_NAME = "memory-hub"

# Make sure the index exists, create it if it doesn't
try:
    # List indexes to check if ours exists
    index_names = [index.name for index in pc.list_indexes()]
    if PINECONE_INDEX_NAME not in index_names:
        logging.info(f"Creating new Pinecone index: {PINECONE_INDEX_NAME}")
        # Create the index with a dimension of 1536 (OpenAI ada embedding dimension)
        # Pinecone free tier only supports 'gcp-starter' environment in one fixed region
        # For Pinecone free tier (gcp-starter)
        pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=1536,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
    logging.info(f"Connected to existing Pinecone index: {PINECONE_INDEX_NAME}")
    index = pc.Index(PINECONE_INDEX_NAME)
except Exception as e:
    logging.error(f"Error with Pinecone index: {e}")
    # Don't crash the entire application if Pinecone setup fails
    # Just log the error and continue
    logging.warning("Continuing without Pinecone index. Vector search will not work.")
    index = None

# OpenAI embedding model
EMBEDDING_MODEL = "text-embedding-ada-002"

def generate_embedding(text: str) -> List[float]:
    """Generate an embedding for the given text using OpenAI"""
    try:
        response = openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logging.error(f"Error generating embedding: {e}")
        raise

def store_embedding(vector: List[float], metadata: Dict[str, Any] = None) -> str:
    """Store a vector in Pinecone and return the vector ID"""
    # Generate a unique ID regardless of whether we can store it
    vector_id = str(uuid.uuid4())
    
    try:
        # Check if index is available (it's set to None in the exception handler above)
        if 'index' not in globals() or index is None:
            logging.warning("Pinecone index not available. Skipping vector storage.")
            return vector_id
            
        # Default empty metadata if None
        if metadata is None:
            metadata = {}
            
        # Get the index
        pinecone_index = pc.Index(PINECONE_INDEX_NAME)
            
        # Upsert the vector
        pinecone_index.upsert(
            vectors=[(vector_id, vector, metadata)]
        )
        
        return vector_id
    except Exception as e:
        logging.error(f"Error storing embedding in Pinecone: {e}")
        # Return the ID even if storage fails
        return vector_id

def similarity_search(query_vector: List[float], top_k: int = 10) -> List[Dict[str, Any]]:
    """Perform a similarity search in Pinecone using the query vector"""
    try:
        # Check if index is available
        if 'index' not in globals() or index is None:
            logging.warning("Pinecone index not available. Returning empty results.")
            return []
            
        # Get the index
        pinecone_index = pc.Index(PINECONE_INDEX_NAME)
        
        # Query the index
        results = pinecone_index.query(
            vector=query_vector,
            top_k=top_k,
            include_metadata=True
        )
        
        return results.get("matches", [])
    except Exception as e:
        logging.error(f"Error performing similarity search in Pinecone: {e}")
        # Return empty results on error
        return []

def process_unstructured_data(content: str) -> Tuple[List[float], str]:
    """Process unstructured data: generate embedding and store in Pinecone"""
    # Generate embedding
    embedding = generate_embedding(content)
    
    # Store in Pinecone
    metadata = {"content_preview": content[:100]}  # Store a preview in metadata
    pinecone_id = store_embedding(embedding, metadata)
    
    return embedding, pinecone_id

def search_by_content(query: str) -> List[Dict[str, Any]]:
    """Search for similar content using a text query"""
    # Generate embedding for the query
    query_embedding = generate_embedding(query)
    
    # Perform similarity search
    results = similarity_search(query_embedding)
    
    return results
    
def get_index_stats() -> Dict[str, Any]:
    """Get statistics about the Pinecone index"""
    try:
        # Check if index is available
        if 'index' not in globals() or index is None:
            logging.warning("Pinecone index not available. Returning empty stats.")
            return {"status": "error", "message": "Pinecone index not available"}
            
        # Get the index
        pinecone_index = pc.Index(PINECONE_INDEX_NAME)
        
        # Get index statistics
        stats = pinecone_index.describe_index_stats()
        
        return {
            "status": "ok",
            "name": PINECONE_INDEX_NAME,
            "vector_count": stats.get("total_vector_count", 0),
            "dimension": stats.get("dimension", 1536)
        }
    except Exception as e:
        logging.error(f"Error getting Pinecone index stats: {e}")
        return {"status": "error", "message": str(e)}


def check_connection() -> Dict[str, Any]:
    """Check the connection to Pinecone and OpenAI.
    
    Returns:
        Status dictionary with connection information
    """
    status = {
        "pinecone": {
            "status": "unknown",
            "message": "",
            "index_name": PINECONE_INDEX_NAME,
            "api_key_configured": bool(os.environ.get("PINECONE_API_KEY"))
        },
        "openai": {
            "status": "unknown",
            "message": "",
            "model": EMBEDDING_MODEL,
            "api_key_configured": bool(os.environ.get("OPENAI_API_KEY"))
        }
    }
    
    # Check Pinecone connection
    try:
        # Try to list indexes
        index_list = pc.list_indexes()
        index_count = len(list(index_list))
        
        # Try to get our specific index
        if 'index' not in globals() or index is None:
            status["pinecone"]["status"] = "error"
            status["pinecone"]["message"] = "Index object not initialized"
        else:
            # Get the index stats for our index
            index_stats = get_index_stats()
            if index_stats.get("status") == "ok":
                status["pinecone"]["status"] = "ok"
                status["pinecone"]["message"] = f"Connected to index with {index_stats.get('vector_count', 0)} vectors"
                status["pinecone"]["vector_count"] = index_stats.get("vector_count", 0)
            else:
                status["pinecone"]["status"] = "error"
                status["pinecone"]["message"] = index_stats.get("message", "Unknown error")
    except Exception as e:
        status["pinecone"]["status"] = "error"
        status["pinecone"]["message"] = str(e)
    
    # Check OpenAI connection
    try:
        # Try to generate a minimal embedding as a connectivity test
        _ = openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input="connectivity test"
        )
        status["openai"]["status"] = "ok"
        status["openai"]["message"] = "Successfully connected to OpenAI API"
    except Exception as e:
        status["openai"]["status"] = "error"
        status["openai"]["message"] = str(e)
    
    return status
