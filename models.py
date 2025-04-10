import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import uuid


@dataclass
class ProjectDecision:
    id: str
    gpt_role: str
    decision_text: str
    context_embedding: List[float]
    related_documents: List[str]
    timestamp: str
    
    @classmethod
    def create(cls, gpt_role: str, decision_text: str, context_embedding: List[float], 
               related_documents: List[str]) -> 'ProjectDecision':
        """Create a new ProjectDecision with auto-generated ID and timestamp"""
        return cls(
            id=str(uuid.uuid4()),
            gpt_role=gpt_role,
            decision_text=decision_text,
            context_embedding=context_embedding,
            related_documents=related_documents,
            timestamp=datetime.now().isoformat()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the object to a dictionary"""
        return {
            'id': self.id,
            'gpt_role': self.gpt_role,
            'decision_text': self.decision_text,
            'context_embedding': self.context_embedding,
            'related_documents': self.related_documents,
            'timestamp': self.timestamp
        }


@dataclass
class UnstructuredData:
    id: str
    content: str
    pinecone_id: str
    
    @classmethod
    def create(cls, content: str, pinecone_id: str) -> 'UnstructuredData':
        """Create a new UnstructuredData with auto-generated ID"""
        return cls(
            id=str(uuid.uuid4()),
            content=content,
            pinecone_id=pinecone_id
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the object to a dictionary"""
        return {
            'id': self.id,
            'content': self.content,
            'pinecone_id': self.pinecone_id
        }


@dataclass
class SharedContext:
    id: str
    sender: str
    recipients: List[str]
    context_tag: str
    memory_refs: List[str]
    timestamp: str
    
    @classmethod
    def create(cls, sender: str, recipients: List[str], context_tag: str, 
               memory_refs: List[str]) -> 'SharedContext':
        """Create a new SharedContext with auto-generated ID and timestamp"""
        return cls(
            id=str(uuid.uuid4()),
            sender=sender,
            recipients=recipients,
            context_tag=context_tag,
            memory_refs=memory_refs,
            timestamp=datetime.now().isoformat()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the object to a dictionary"""
        return {
            'id': self.id,
            'sender': self.sender,
            'recipients': self.recipients,
            'context_tag': self.context_tag,
            'memory_refs': self.memory_refs,
            'timestamp': self.timestamp
        }
