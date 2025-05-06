import json
import os
import requests
from typing import Dict, List, Any, Optional
import time

# API base URL - replace with your actual URL
API_BASE = "http://localhost:5000"
API_KEY = os.environ.get("API_KEY")  # Get API key from environment

headers = {
    "Content-Type": "application/json",
    "X-API-KEY": API_KEY
}

def create_agent_session(agent_id: str, user_id: Optional[str] = None, 
                        current_focus: Optional[str] = None) -> Dict[str, Any]:
    """Create a new agent session"""
    data = {
        "agent_id": agent_id,
        "user_id": user_id,
        "current_focus": current_focus,
        "active_context_tags": ["project_overview", "task_discussion"]
    }
    
    response = requests.post(f"{API_BASE}/agent/sessions", 
                             headers=headers, 
                             json=data)
    
    if response.status_code == 201:
        return response.json()
    else:
        raise Exception(f"Failed to create session: {response.text}")

def add_message_to_session(session_id: str, sender: str, message_type: str, 
                          content: str, receiver: Optional[str] = None) -> Dict[str, Any]:
    """Add a message to a session"""
    data = {
        "sender_agent": sender,
        "receiver_agent": receiver,
        "message_type": message_type,
        "content": content,
        "session_id": session_id
    }
    
    response = requests.post(f"{API_BASE}/agent/messages", 
                             headers=headers, 
                             json=data)
    
    if response.status_code == 201:
        return response.json()
    else:
        raise Exception(f"Failed to add message: {response.text}")

def get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    """Get all messages in a session"""
    response = requests.get(f"{API_BASE}/agent/sessions/{session_id}/messages", 
                           headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to get messages: {response.text}")

def end_session(session_id: str) -> Dict[str, Any]:
    """End an agent session"""
    response = requests.put(f"{API_BASE}/agent/sessions/{session_id}/end", 
                           headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to end session: {response.text}")

def create_knowledge_entry(term: str, defined_by_file: Optional[str] = None,
                          used_by_agents: Optional[List[str]] = None,
                          synonyms: Optional[List[str]] = None) -> Dict[str, Any]:
    """Create a knowledge index entry"""
    data = {
        "term": term,
        "defined_by_file": defined_by_file,
        "used_by_agents": used_by_agents or [],
        "synonyms": synonyms or [],
        "relevance_score": 5
    }
    
    response = requests.post(f"{API_BASE}/kb/entries", 
                             headers=headers, 
                             json=data)
    
    if response.status_code == 201:
        return response.json()
    else:
        raise Exception(f"Failed to create knowledge entry: {response.text}")

def log_decision(agent: str, context: str, decision_text: str, 
                impact_area: Optional[str] = None) -> Dict[str, Any]:
    """Log a decision made by an agent"""
    data = {
        "made_by_agent": agent,
        "context": context,
        "decision_text": decision_text,
        "impact_area": impact_area,
        "reversal_possible": True
    }
    
    response = requests.post(f"{API_BASE}/decisions", 
                             headers=headers, 
                             json=data)
    
    if response.status_code == 201:
        return response.json()
    else:
        raise Exception(f"Failed to log decision: {response.text}")

def main():
    """Example workflow demonstrating multi-agent communication"""
    try:
        # Create a session for the product manager agent
        pm_session = create_agent_session(
            agent_id="product_gpt",
            user_id="user123",
            current_focus="feature_planning"
        )
        pm_session_id = pm_session["session_id"]
        print(f"Created PM session: {pm_session_id}")
        
        # Create a session for the developer agent
        dev_session = create_agent_session(
            agent_id="developer_gpt",
            current_focus="implementation"
        )
        dev_session_id = dev_session["session_id"]
        print(f"Created Developer session: {dev_session_id}")
        
        # PM creates a knowledge entry
        kb_entry = create_knowledge_entry(
            term="user authentication flow",
            defined_by_file="auth_spec.md",
            used_by_agents=["product_gpt", "developer_gpt"],
            synonyms=["login flow", "auth process"]
        )
        print(f"Created knowledge entry: {kb_entry['index_id']}")
        
        # PM sends a task to the developer
        pm_message = add_message_to_session(
            session_id=pm_session_id,
            sender="product_gpt",
            receiver="developer_gpt",
            message_type="instruction",
            content="Please implement the user authentication flow as specified in auth_spec.md."
        )
        print(f"PM sent message: {pm_message['message_id']}")
        
        # Developer acknowledges receipt
        dev_message = add_message_to_session(
            session_id=dev_session_id,
            sender="developer_gpt",
            receiver="product_gpt",
            message_type="status_update",
            content="Received the task. I'll begin implementing the authentication flow now."
        )
        print(f"Developer sent message: {dev_message['message_id']}")
        
        # Developer logs a decision
        decision = log_decision(
            agent="developer_gpt",
            context="auth implementation",
            decision_text="Will use JWT tokens for authentication to improve scalability",
            impact_area="authentication"
        )
        print(f"Developer logged decision: {decision['decision_id']}")
        
        # Wait a moment
        time.sleep(1)
        
        # Get conversation history from PM session
        pm_messages = get_session_messages(pm_session_id)
        print(f"PM session has {len(pm_messages)} messages:")
        for msg in pm_messages:
            print(f"  - {msg['sender_agent']} to {msg['receiver_agent']}: {msg['content']}")
        
        # End the sessions when done
        pm_end = end_session(pm_session_id)
        dev_end = end_session(dev_session_id)
        print(f"Sessions ended. PM: {pm_end['session_id']}, Dev: {dev_end['session_id']}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()