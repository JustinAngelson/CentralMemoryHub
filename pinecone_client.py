import os
import logging
import json
from typing import List, Dict, Any, Optional, Tuple
import uuid
import requests
from openai import OpenAI

# Initialize the OpenAI client
# The newest OpenAI model is "gpt-4o" which was released May 13, 2024.
# Do not change this unless explicitly requested by the user
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Pinecone constants
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_ENVIRONMENT = os.environ.get("PINECONE_ENVIRONMENT", "us-west1-gcp")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "memory-hub")

# Headers for Pinecone API requests
PINECONE_HEADERS = {
    "Api-Key": PINECONE_API_KEY,
    "Content-Type": "application/json"
}

# OpenAI embedding model
EMBEDDING_MODEL = "text-embedding-ada-002"

def get_pinecone_base_url() -> str:
    """Get the base URL for Pinecone API calls"""
    return f"https://{PINECONE_INDEX_NAME}-{PINECONE_ENVIRONMENT}.svc.pinecone.io"

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
    try:
        vector_id = str(uuid.uuid4())
        url = f"{get_pinecone_base_url()}/vectors/upsert"
        
        payload = {
            "vectors": [{
                "id": vector_id,
                "values": vector,
                "metadata": metadata or {}
            }]
        }
        
        response = requests.post(url, headers=PINECONE_HEADERS, json=payload)
        response.raise_for_status()
        
        return vector_id
    except Exception as e:
        logging.error(f"Error storing embedding in Pinecone: {e}")
        raise

def similarity_search(query_vector: List[float], top_k: int = 10) -> List[Dict[str, Any]]:
    """Perform a similarity search in Pinecone using the query vector"""
    try:
        url = f"{get_pinecone_base_url()}/query"
        
        payload = {
            "vector": query_vector,
            "topK": top_k,
            "includeMetadata": True
        }
        
        response = requests.post(url, headers=PINECONE_HEADERS, json=payload)
        response.raise_for_status()
        
        result = response.json()
        return result.get("matches", [])
    except Exception as e:
        logging.error(f"Error performing similarity search in Pinecone: {e}")
        raise

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
