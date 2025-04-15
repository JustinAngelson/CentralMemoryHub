import json
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid
from sqlalchemy import Column, String, Text, JSON, DateTime
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import ARRAY
from app import db


class ProjectDecision(db.Model):
    __tablename__ = 'project_decisions'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    gpt_role = Column(String(100), nullable=False)
    decision_text = Column(Text, nullable=False)
    context_embedding = Column(JSON, nullable=False)  # Store as JSON array in PostgreSQL
    related_documents = Column(JSON, nullable=False)  # Store as JSON array in PostgreSQL
    timestamp = Column(DateTime, default=func.now())
    
    @classmethod
    def create(cls, gpt_role: str, decision_text: str, context_embedding: List[float], 
               related_documents: List[str]) -> 'ProjectDecision':
        """Create a new ProjectDecision with auto-generated ID and timestamp"""
        return cls(
            id=str(uuid.uuid4()),
            gpt_role=gpt_role,
            decision_text=decision_text,
            context_embedding=context_embedding,
            related_documents=related_documents
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the object to a dictionary"""
        return {
            'id': self.id,
            'gpt_role': self.gpt_role,
            'decision_text': self.decision_text,
            'context_embedding': self.context_embedding,
            'related_documents': self.related_documents,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }


class UnstructuredData(db.Model):
    __tablename__ = 'unstructured_data'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    content = Column(Text, nullable=False)
    pinecone_id = Column(String(36), nullable=False)
    
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


class SharedContext(db.Model):
    __tablename__ = 'shared_contexts'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sender = Column(String(100), nullable=False)
    recipients = Column(JSON, nullable=False)  # Store as JSON array in PostgreSQL
    context_tag = Column(String(100), nullable=False)
    memory_refs = Column(JSON, nullable=False)  # Store as JSON array in PostgreSQL
    timestamp = Column(DateTime, default=func.now())
    
    @classmethod
    def create(cls, sender: str, recipients: List[str], context_tag: str, 
               memory_refs: List[str]) -> 'SharedContext':
        """Create a new SharedContext with auto-generated ID and timestamp"""
        return cls(
            id=str(uuid.uuid4()),
            sender=sender,
            recipients=recipients,
            context_tag=context_tag,
            memory_refs=memory_refs
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the object to a dictionary"""
        return {
            'id': self.id,
            'sender': self.sender,
            'recipients': self.recipients,
            'context_tag': self.context_tag,
            'memory_refs': self.memory_refs,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }
