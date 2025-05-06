import json
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import uuid
from sqlalchemy import Column, String, Text, JSON, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, backref
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app import db


# Existing Models
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
    pinecone_id = Column(String(36), nullable=False, unique=True, index=True)  # Make unique for FK relationship
    
    # Relationship with memory_links (one-to-many)
    memory_links = relationship("MemoryLink", back_populates="unstructured_data")
    
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


# New Models as per the PostgreSQL enhancement plan

class AgentDirectory(db.Model):
    """
    Directory of AI agents and their relationships (AI Org Chart)
    """
    __tablename__ = 'agent_directory'

    agent_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, unique=True)
    role = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    capabilities = Column(JSONB, nullable=True)  # ["code_generation", "task_planning", "summarization"]
    reports_to = Column(String(36), ForeignKey('agent_directory.agent_id'), nullable=True)
    seniority_level = Column(Integer, default=1)  # 1=entry level, 5=executive
    status = Column(String(20), default="active")  # active, inactive, in_training
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    subordinates = relationship(
        "AgentDirectory", 
        foreign_keys="AgentDirectory.reports_to"
    )
    sessions = relationship("AgentSession", back_populates="agent")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'agent_id': self.agent_id,
            'name': self.name,
            'role': self.role,
            'description': self.description,
            'capabilities': self.capabilities,
            'reports_to': self.reports_to,
            'seniority_level': self.seniority_level,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'subordinate_count': len(self.subordinates) if self.subordinates else 0
        }

class AgentSession(db.Model):
    """
    Track what each GPT sees, does, and says during every session.
    """
    __tablename__ = 'agent_sessions'
    
    session_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String(36), ForeignKey('agent_directory.agent_id'), nullable=False, index=True)
    started_at = Column(DateTime, default=func.now())
    ended_at = Column(DateTime, nullable=True)
    user_id = Column(String(100), nullable=True, index=True)  # if interactive
    current_focus = Column(String(255), nullable=True)  # e.g., spec review, ops report
    summary_notes = Column(Text, nullable=True)
    active_context_tags = Column(JSONB, nullable=True)  # ["inventory", "traceability", "clientX"]
    
    # Relationships
    messages = relationship("GPTMessage", back_populates="session")
    agent = relationship("AgentDirectory", back_populates="sessions")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'session_id': self.session_id,
            'agent_id': self.agent_id,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'user_id': self.user_id,
            'current_focus': self.current_focus,
            'summary_notes': self.summary_notes,
            'active_context_tags': self.active_context_tags
        }


class GPTMessage(db.Model):
    """
    Log all inter-agent and agent-user communication.
    """
    __tablename__ = 'gpt_messages'
    
    message_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sender_agent = Column(String(100), nullable=False, index=True)
    receiver_agent = Column(String(100), nullable=True, index=True)  # nullable for user-facing messages
    timestamp = Column(DateTime, default=func.now(), index=True)
    message_type = Column(String(50), nullable=False)  # instruction, status_update, handoff, question
    content = Column(Text, nullable=False)
    session_id = Column(String(36), ForeignKey('agent_sessions.session_id'), nullable=False)
    
    # Relationships
    session = relationship("AgentSession", back_populates="messages")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'message_id': self.message_id,
            'sender_agent': self.sender_agent,
            'receiver_agent': self.receiver_agent,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'message_type': self.message_type,
            'content': self.content,
            'session_id': self.session_id
        }


class OrgState(db.Model):
    """
    Store a snapshot of your business from the AI's perspective.
    """
    __tablename__ = 'org_state'
    
    entity_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity = Column(String(255), nullable=False, index=True)  # e.g., CMKY Project, Client: Alovea
    type = Column(String(50), nullable=False, index=True)  # project, client, internal_initiative
    status = Column(String(50), nullable=False, index=True)  # active, paused, complete
    summary = Column(Text, nullable=True)
    owner_agent = Column(String(100), nullable=False, index=True)
    last_updated_by = Column(String(100), nullable=False)
    important_dates = Column(JSONB, nullable=True)  # {"kickoff": "2024-06-01", "go_live": "2024-09-01"}
    linked_docs = Column(JSONB, nullable=True)  # [filenames or WorkDrive links]
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'entity_id': self.entity_id,
            'entity': self.entity,
            'type': self.type,
            'status': self.status,
            'summary': self.summary,
            'owner_agent': self.owner_agent,
            'last_updated_by': self.last_updated_by,
            'important_dates': self.important_dates,
            'linked_docs': self.linked_docs,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class AgentTask(db.Model):
    """
    Let GPTs track, assign, escalate, and summarize work.
    """
    __tablename__ = 'agent_tasks'
    
    task_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    assigned_to_agent = Column(String(100), nullable=False, index=True)
    created_by_agent = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, index=True)  # todo, in_progress, waiting, done
    priority = Column(Integer, nullable=True)
    linked_project = Column(String(255), nullable=True, index=True)
    summary_notes = Column(Text, nullable=True)
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'task_id': self.task_id,
            'title': self.title,
            'description': self.description,
            'assigned_to_agent': self.assigned_to_agent,
            'created_by_agent': self.created_by_agent,
            'status': self.status,
            'priority': self.priority,
            'linked_project': self.linked_project,
            'summary_notes': self.summary_notes,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class DecisionLog(db.Model):
    """
    Store who made which decision, why, and when.
    """
    __tablename__ = 'decision_log'
    
    decision_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    context = Column(String(255), nullable=False)  # e.g., product spec template change
    made_by_agent = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime, default=func.now(), index=True)
    decision_text = Column(Text, nullable=False)
    impact_area = Column(String(255), nullable=True)
    reversal_possible = Column(Boolean, default=True)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'decision_id': self.decision_id,
            'context': self.context,
            'made_by_agent': self.made_by_agent,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'decision_text': self.decision_text,
            'impact_area': self.impact_area,
            'reversal_possible': self.reversal_possible
        }


class KnowledgeIndex(db.Model):
    """
    Map terms, tags, and documents to source locations and trust levels.
    """
    __tablename__ = 'kb_index'
    
    index_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    term = Column(String(255), nullable=False, index=True)  # composite spec
    defined_by_file = Column(String(255), nullable=True)
    used_by_agents = Column(JSONB, nullable=True)  # ["cto_gpt", "product_gpt"]
    relevance_score = Column(Integer, nullable=True)
    last_verified = Column(DateTime, nullable=True)
    synonyms = Column(JSONB, nullable=True)  # ["item spec", "spec sheet"]
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'index_id': self.index_id,
            'term': self.term,
            'defined_by_file': self.defined_by_file,
            'used_by_agents': self.used_by_agents,
            'relevance_score': self.relevance_score,
            'last_verified': self.last_verified.isoformat() if self.last_verified else None,
            'synonyms': self.synonyms,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class MemoryLink(db.Model):
    """
    Link Pinecone insights into structured logs.
    """
    __tablename__ = 'memory_links'
    
    link_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pinecone_vector_id = Column(String(36), ForeignKey('unstructured_data.pinecone_id'), nullable=False)
    summary = Column(Text, nullable=True)
    linked_agent_event = Column(String(36), nullable=True)  # could be session_id, message_id, etc.
    origin_file_or_source = Column(String(255), nullable=True)
    timestamp_added = Column(DateTime, default=func.now())
    
    # Relationships
    unstructured_data = relationship("UnstructuredData", back_populates="memory_links")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'link_id': self.link_id,
            'pinecone_vector_id': self.pinecone_vector_id,
            'summary': self.summary,
            'linked_agent_event': self.linked_agent_event,
            'origin_file_or_source': self.origin_file_or_source,
            'timestamp_added': self.timestamp_added.isoformat() if self.timestamp_added else None
        }


class Experiment(db.Model):
    """
    Let your agents learn like scientists — track trials and feedback.
    """
    __tablename__ = 'experiments'
    
    experiment_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    hypothesis = Column(Text, nullable=False)
    executing_agent = Column(String(100), nullable=False, index=True)
    outcome = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, index=True)  # planned, running, complete, failed
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'experiment_id': self.experiment_id,
            'title': self.title,
            'description': self.description,
            'hypothesis': self.hypothesis,
            'executing_agent': self.executing_agent,
            'outcome': self.outcome,
            'notes': self.notes,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class UserInsight(db.Model):
    """
    Track user behaviors, prompts, preferences.
    """
    __tablename__ = 'user_insights'
    
    insight_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, index=True)
    interaction_type = Column(String(100), nullable=False)  # prompt, feedback, manual_override
    summary = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=func.now(), index=True)
    related_agent_or_project = Column(String(255), nullable=True)
    result = Column(Text, nullable=True)
    tone_tag = Column(String(50), nullable=True)  # frustrated, in flow, curious
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'insight_id': self.insight_id,
            'user_id': self.user_id,
            'interaction_type': self.interaction_type,
            'summary': self.summary,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'related_agent_or_project': self.related_agent_or_project,
            'result': self.result,
            'tone_tag': self.tone_tag
        }
