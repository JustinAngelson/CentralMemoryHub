#!/usr/bin/env python3
"""
Memory Hub API Client Example

This script demonstrates how to interact with the Memory Hub API using Python.
It's designed to help you understand how to integrate the Memory Hub with your Custom GPT.
"""

import json
import uuid
import requests
from typing import Dict, List, Any, Optional
from datetime import datetime

class MemoryHubClient:
    """Client for the Memory Hub API."""
    
    def __init__(self, api_key: str, base_url: str = "https://memory-vault-angelson.replit.app"):
        """
        Initialize the Memory Hub client.
        
        Args:
            api_key: Your API key for authentication
            base_url: The base URL of the Memory Hub API
        """
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Content-Type": "application/json",
            "X-API-KEY": api_key  # Note: The header must be all caps X-API-KEY
        }
        # Set default request headers for authentication
    
    def check_health(self) -> Dict[str, Any]:
        """
        Check the health of the Memory Hub API.
        This endpoint doesn't require authentication.
        
        Returns:
            Dict containing system health status
        """
        url = f"{self.base_url}/sys/health"
        response = requests.get(url)
        return self._process_response(response)
    
    def store_memory(self, content: str) -> Dict[str, Any]:
        """
        Store unstructured data in the Memory Hub.
        
        Args:
            content: The content to store
            
        Returns:
            Dict containing the ID and status of the created memory
        """
        url = f"{self.base_url}/memory/unstructured"
        data = {"content": content}
        response = requests.post(url, headers=self.headers, json=data)
        return self._process_response(response)
    
    def get_memory(self, memory_id: str) -> Dict[str, Any]:
        """
        Retrieve a specific memory by ID.
        
        Args:
            memory_id: The ID of the memory to retrieve
            
        Returns:
            Dict containing the memory data
        """
        url = f"{self.base_url}/memory/unstructured/{memory_id}"
        response = requests.get(url, headers=self.headers)
        return self._process_response(response)
    
    def search_memories(self, query: str) -> Dict[str, Any]:
        """
        Search for memories using semantic similarity.
        
        Args:
            query: The search query
            
        Returns:
            Dict containing search results
        """
        url = f"{self.base_url}/search"
        data = {"query": query}
        response = requests.post(url, headers=self.headers, json=data)
        return self._process_response(response)
    
    def get_agent_directory(self) -> List[Dict[str, Any]]:
        """
        Get all agents in the directory.
        
        Returns:
            List of agents in the directory
        """
        url = f"{self.base_url}/api/directory"
        response = requests.get(url, headers=self.headers)
        return self._process_response(response)
    
    def add_agent(self, 
                 name: str, 
                 role: str, 
                 description: str, 
                 capabilities: Optional[List[str]] = None,
                 reports_to: Optional[str] = None,
                 seniority_level: Optional[int] = None,
                 status: str = "active") -> Dict[str, Any]:
        """
        Add a new agent to the directory.
        
        Args:
            name: Name of the agent
            role: Role of the agent
            description: Description of the agent
            capabilities: List of capabilities (optional)
            reports_to: ID of the agent this agent reports to (optional)
            seniority_level: Seniority level 1-5 (optional)
            status: Status of the agent, active or inactive (default: active)
            
        Returns:
            Dict containing the created agent data
        """
        url = f"{self.base_url}/api/directory"
        data = {
            "name": name,
            "role": role,
            "description": description,
            "status": status
        }
        
        if capabilities:
            data["capabilities"] = capabilities  # This will be properly serialized to JSON by requests
        if reports_to:
            data["reports_to"] = reports_to
        if seniority_level is not None:
            data["seniority_level"] = seniority_level  # This will be properly serialized to JSON by requests
            
        response = requests.post(url, headers=self.headers, json=data)
        return self._process_response(response)
    
    def _process_response(self, response: requests.Response) -> Any:
        """
        Process the API response.
        
        Args:
            response: The response object from requests
            
        Returns:
            Parsed JSON response
            
        Raises:
            Exception: If the API request failed
        """
        try:
            if response.status_code >= 400:
                error_msg = response.json().get('message', 'Unknown error')
                raise Exception(f"API Error ({response.status_code}): {error_msg}")
            return response.json()
        except json.JSONDecodeError:
            raise Exception(f"Invalid JSON response: {response.text}")


def main():
    """Run a demonstration of the Memory Hub client."""
    # Replace with your actual API key
    api_key = "your-api-key-here"
    client = MemoryHubClient(api_key)
    
    print("Memory Hub API Client Demo")
    print("==========================")
    
    # Check system health (doesn't require auth)
    print("\n1. Checking system health...")
    health = client.check_health()
    print(f"System status: {health['status']}")
    print(f"Components: {health['components']}")
    
    # Store a memory
    print("\n2. Storing a memory...")
    timestamp = datetime.now().isoformat()
    memory = client.store_memory(
        f"This is a test memory created through the Python client at {timestamp}"
    )
    memory_id = memory["id"]
    print(f"Created memory with ID: {memory_id}")
    
    # Retrieve the memory
    print("\n3. Retrieving the memory...")
    retrieved = client.get_memory(memory_id)
    print(f"Retrieved content: {retrieved['content']}")
    
    # Search for memories
    print("\n4. Searching for memories...")
    results = client.search_memories("test memory")
    print(f"Found {len(results['results'])} results")
    for i, result in enumerate(results['results']):
        print(f"Result {i+1}: {result['content']} (score: {result['similarity_score']})")
    
    # Get agent directory
    print("\n5. Getting agent directory...")
    agents = client.get_agent_directory()
    print(f"Found {len(agents)} agents")
    for i, agent in enumerate(agents):
        print(f"Agent {i+1}: {agent['name']} ({agent['role']})")
    
    print("\nDemo completed!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}")