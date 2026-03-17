"""
Organization tools for the Central Memory Hub MCP Server.

10 tools covering shared context, org state, decision logging,
knowledge indexing, and memory links.
"""
import json
import uuid
import logging
from typing import Optional, List, Dict
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

from mcp_tools import (
    get_db_session,
    SharedContext, OrgState, DecisionLog, KnowledgeIndex, MemoryLink,
)


# ────────────────────────────────────────────────────────────────────
# Pydantic Input Models
# ────────────────────────────────────────────────────────────────────

class ShareContextInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    sender: str = Field(..., min_length=1, description="Sending agent identifier")
    recipients: List[str] = Field(..., min_length=1, description="Target agents")
    context_tag: str = Field(..., max_length=100, description="Descriptive tag for this context entry")
    memory_refs: List[str] = Field(..., min_length=1, description="Memory IDs being referenced")


class CreateOrgStateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    entity: str = Field(..., min_length=1, description="Entity name (e.g., 'Project Alpha', 'Client: Alovea')")
    type: str = Field(..., min_length=1, description="Entity type: client, project, infrastructure, process")
    status: str = Field(..., min_length=1, description="Current status (active, paused, complete, etc.)")
    owner_agent: str = Field(..., min_length=1, description="Primary responsible agent")
    last_updated_by: str = Field(..., min_length=1, description="Agent making this update")
    summary: Optional[str] = Field(None, description="Brief description of the entity's state")
    important_dates: Optional[Dict[str, str]] = Field(None, description="Key dates as {label: ISO date string}")
    linked_docs: Optional[List[str]] = Field(None, description="Document references or links")


class UpdateOrgStateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    entity_id: str = Field(..., min_length=1, description="UUID of the org state entry to update")
    last_updated_by: str = Field(..., min_length=1, description="Agent making this update")
    status: Optional[str] = Field(None, description="New status value")
    summary: Optional[str] = Field(None, description="Updated summary")
    owner_agent: Optional[str] = Field(None, description="New owner agent")
    important_dates: Optional[Dict[str, str]] = Field(None, description="Updated key dates")
    linked_docs: Optional[List[str]] = Field(None, description="Updated document references")


class ListOrgStatesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    type: Optional[str] = Field(None, description="Filter by entity type")
    status: Optional[str] = Field(None, description="Filter by status")
    owner_agent: Optional[str] = Field(None, description="Filter by owner agent")


class LogDecisionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    context: str = Field(..., min_length=1, description="Situation or context for this decision")
    made_by_agent: str = Field(..., min_length=1, description="Agent who made the decision")
    decision_text: str = Field(..., min_length=1, description="The decision itself")
    impact_area: Optional[str] = Field(None, description="Area impacted by this decision")
    reversal_possible: Optional[bool] = Field(True, description="Whether this decision can be reversed")


class ListDecisionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    made_by_agent: Optional[str] = Field(None, description="Filter by decision-making agent")
    impact_area: Optional[str] = Field(None, description="Filter by impact area")
    reversal_possible: Optional[str] = Field(None, description="Filter by reversibility: 'true' or 'false'")
    from_date: Optional[str] = Field(None, description="ISO date string — only return decisions after this date")
    to_date: Optional[str] = Field(None, description="ISO date string — only return decisions before this date")


class StoreKnowledgeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    term: str = Field(..., min_length=1, description="The knowledge term to index")
    defined_by_file: Optional[str] = Field(None, description="Source file that defines this term")
    used_by_agents: Optional[List[str]] = Field(None, description="Agents that use this term")
    relevance_score: Optional[int] = Field(None, ge=1, le=10, description="Relevance score 1-10")
    synonyms: Optional[List[str]] = Field(None, description="Alternate names for this term")


class SearchKnowledgeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    term: Optional[str] = Field(None, description="Partial match on term name")
    agent: Optional[str] = Field(None, description="Filter by agent that uses this term")
    min_relevance: Optional[int] = Field(None, ge=1, le=10, description="Minimum relevance score 1-10")


class CreateMemoryLinkInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    pinecone_vector_id: str = Field(..., min_length=1, description="Pinecone vector ID to link")
    summary: Optional[str] = Field(None, description="Brief summary of this memory link")
    linked_agent_event: Optional[str] = Field(None, description="Associated session_id or message_id")
    origin_file_or_source: Optional[str] = Field(None, description="Source file or origin of the memory")


class ListMemoryLinksInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    pinecone_vector_id: Optional[str] = Field(None, description="Filter by Pinecone vector ID")
    linked_agent_event: Optional[str] = Field(None, description="Filter by linked session or message ID")
    origin_file_or_source: Optional[str] = Field(None, description="Filter by source file or origin")


# ────────────────────────────────────────────────────────────────────
# Tool Registrations
# ────────────────────────────────────────────────────────────────────

def register_organization_tools(mcp: FastMCP) -> None:
    """Register all organization tools with the MCP server."""

    @mcp.tool(
        name="cmh_share_context",
        annotations={
            "title": "Share Context",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_share_context(params: ShareContextInput) -> str:
        """Create a cross-agent context entry linking agents to tagged memory references.

        Use to broadcast a set of memory IDs to one or more agents with a shared tag
        so they can orient themselves to a topic without re-searching.

        Args:
            params: ShareContextInput with:
                - sender (str): Sending agent identifier
                - recipients (List[str]): Target agent identifiers
                - context_tag (str): Descriptive label for this context
                - memory_refs (List[str]): Memory UUIDs being shared

        Returns:
            Confirmation with the new SharedContext ID.
        """
        session = get_db_session()
        try:
            record = SharedContext(
                id=str(uuid.uuid4()),
                sender=params.sender,
                recipients=params.recipients,
                context_tag=params.context_tag,
                memory_refs=params.memory_refs,
            )
            session.add(record)
            session.commit()
            return f"Context shared successfully.\nID: {record.id}\nTag: {params.context_tag}\nRecipients: {', '.join(params.recipients)}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_share_context error: {e}")
            return f"Error sharing context: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_list_contexts",
        annotations={
            "title": "List Shared Contexts",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_list_contexts() -> str:
        """Retrieve all shared context entries.

        Returns a list of all cross-agent context broadcasts, sorted newest first.

        Returns:
            JSON array of SharedContext records.
        """
        session = get_db_session()
        try:
            entries = session.query(SharedContext).order_by(SharedContext.timestamp.desc()).all()
            if not entries:
                return "No shared contexts found."
            return json.dumps([e.to_dict() for e in entries], indent=2)
        except Exception as e:
            logging.error(f"cmh_list_contexts error: {e}")
            return f"Error listing contexts: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_create_org_state",
        annotations={
            "title": "Create Org State",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_create_org_state(params: CreateOrgStateInput) -> str:
        """Track the state of a project, client, or other organizational entity.

        Creates a snapshot of the entity's current status, ownership, and key dates
        that any agent can query to understand where things stand.

        Args:
            params: CreateOrgStateInput with entity, type, status, owner_agent,
                    last_updated_by, and optional summary, important_dates, linked_docs.

        Returns:
            Confirmation with the new entity_id.
        """
        session = get_db_session()
        try:
            record = OrgState(
                entity_id=str(uuid.uuid4()),
                entity=params.entity,
                type=params.type,
                status=params.status,
                owner_agent=params.owner_agent,
                last_updated_by=params.last_updated_by,
                summary=params.summary,
                important_dates=params.important_dates,
                linked_docs=params.linked_docs,
            )
            session.add(record)
            session.commit()
            return f"Org state created.\nEntity ID: {record.entity_id}\nEntity: {params.entity}\nStatus: {params.status}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_create_org_state error: {e}")
            return f"Error creating org state: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_update_org_state",
        annotations={
            "title": "Update Org State",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_update_org_state(params: UpdateOrgStateInput) -> str:
        """Update an existing org state entry.

        Only provided fields are updated; omitted fields remain unchanged.

        Args:
            params: UpdateOrgStateInput with entity_id, last_updated_by, and any
                    optional fields to update (status, summary, owner_agent,
                    important_dates, linked_docs).

        Returns:
            Confirmation or error message.
        """
        session = get_db_session()
        try:
            entry = session.query(OrgState).get(params.entity_id)
            if not entry:
                return f"Org state not found: {params.entity_id}"

            entry.last_updated_by = params.last_updated_by
            if params.status is not None:
                entry.status = params.status
            if params.summary is not None:
                entry.summary = params.summary
            if params.owner_agent is not None:
                entry.owner_agent = params.owner_agent
            if params.important_dates is not None:
                entry.important_dates = params.important_dates
            if params.linked_docs is not None:
                entry.linked_docs = params.linked_docs

            session.commit()
            return f"Org state updated.\nEntity: {entry.entity}\nStatus: {entry.status}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_update_org_state error: {e}")
            return f"Error updating org state: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_list_org_states",
        annotations={
            "title": "List Org States",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_list_org_states(params: ListOrgStatesInput) -> str:
        """List org states with optional filters.

        Args:
            params: ListOrgStatesInput with optional type, status, owner_agent filters.

        Returns:
            JSON array of matching OrgState records, sorted newest first.
        """
        session = get_db_session()
        try:
            query = session.query(OrgState)
            if params.type:
                query = query.filter(OrgState.type == params.type)
            if params.status:
                query = query.filter(OrgState.status == params.status)
            if params.owner_agent:
                query = query.filter(OrgState.owner_agent == params.owner_agent)

            entries = query.order_by(OrgState.updated_at.desc()).all()
            if not entries:
                return "No org states found matching your filters."
            return json.dumps([e.to_dict() for e in entries], indent=2)
        except Exception as e:
            logging.error(f"cmh_list_org_states error: {e}")
            return f"Error listing org states: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_log_decision",
        annotations={
            "title": "Log Decision",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_log_decision(params: LogDecisionInput) -> str:
        """Record a decision with full context and attribution.

        Captures who made a decision, the context around it, whether it can
        be reversed, and what area it impacts. Builds an auditable decision trail.

        Args:
            params: LogDecisionInput with context, made_by_agent, decision_text,
                    and optional impact_area, reversal_possible.

        Returns:
            Confirmation with new decision_id.
        """
        session = get_db_session()
        try:
            record = DecisionLog(
                decision_id=str(uuid.uuid4()),
                context=params.context,
                made_by_agent=params.made_by_agent,
                decision_text=params.decision_text,
                impact_area=params.impact_area,
                reversal_possible=params.reversal_possible if params.reversal_possible is not None else True,
            )
            session.add(record)
            session.commit()
            return f"Decision logged.\nDecision ID: {record.decision_id}\nMade by: {params.made_by_agent}\nReversible: {record.reversal_possible}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_log_decision error: {e}")
            return f"Error logging decision: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_list_decisions",
        annotations={
            "title": "List Decisions",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_list_decisions(params: ListDecisionsInput) -> str:
        """List the decision log with optional filters.

        Args:
            params: ListDecisionsInput with optional made_by_agent, impact_area,
                    reversal_possible ('true'/'false'), from_date, to_date (ISO strings).

        Returns:
            JSON array of matching DecisionLog records, sorted newest first.
        """
        session = get_db_session()
        try:
            query = session.query(DecisionLog)
            if params.made_by_agent:
                query = query.filter(DecisionLog.made_by_agent == params.made_by_agent)
            if params.impact_area:
                query = query.filter(DecisionLog.impact_area == params.impact_area)
            if params.reversal_possible is not None:
                rev = params.reversal_possible.lower() == "true"
                query = query.filter(DecisionLog.reversal_possible == rev)
            if params.from_date:
                query = query.filter(DecisionLog.timestamp >= datetime.fromisoformat(params.from_date))
            if params.to_date:
                query = query.filter(DecisionLog.timestamp <= datetime.fromisoformat(params.to_date))

            entries = query.order_by(DecisionLog.timestamp.desc()).all()
            if not entries:
                return "No decisions found matching your filters."
            return json.dumps([e.to_dict() for e in entries], indent=2)
        except Exception as e:
            logging.error(f"cmh_list_decisions error: {e}")
            return f"Error listing decisions: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_store_knowledge",
        annotations={
            "title": "Store Knowledge Term",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_store_knowledge(params: StoreKnowledgeInput) -> str:
        """Index a knowledge term with provenance and usage tracking.

        Use to register domain-specific terminology, concepts, or acronyms
        so all agents share a common vocabulary and can look up definitions.

        Args:
            params: StoreKnowledgeInput with term and optional defined_by_file,
                    used_by_agents, relevance_score (1-10), synonyms.

        Returns:
            Confirmation with new index_id.
        """
        session = get_db_session()
        try:
            record = KnowledgeIndex(
                index_id=str(uuid.uuid4()),
                term=params.term,
                defined_by_file=params.defined_by_file,
                used_by_agents=params.used_by_agents,
                relevance_score=params.relevance_score,
                synonyms=params.synonyms,
            )
            session.add(record)
            session.commit()
            return f"Knowledge term stored.\nIndex ID: {record.index_id}\nTerm: {params.term}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_store_knowledge error: {e}")
            return f"Error storing knowledge term: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_search_knowledge",
        annotations={
            "title": "Search Knowledge Index",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_search_knowledge(params: SearchKnowledgeInput) -> str:
        """Search the knowledge index by term, agent usage, or relevance score.

        Args:
            params: SearchKnowledgeInput with optional term (partial match),
                    agent (agent that uses the term), min_relevance (1-10).

        Returns:
            JSON array of matching KnowledgeIndex records.
        """
        session = get_db_session()
        try:
            query = session.query(KnowledgeIndex)
            if params.term:
                query = query.filter(KnowledgeIndex.term.ilike(f"%{params.term}%"))
            if params.agent:
                query = query.filter(KnowledgeIndex.used_by_agents.contains([params.agent]))
            if params.min_relevance is not None:
                query = query.filter(KnowledgeIndex.relevance_score >= params.min_relevance)

            entries = query.order_by(KnowledgeIndex.relevance_score.desc()).all()
            if not entries:
                return "No knowledge terms found matching your query."
            return json.dumps([e.to_dict() for e in entries], indent=2)
        except Exception as e:
            logging.error(f"cmh_search_knowledge error: {e}")
            return f"Error searching knowledge index: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_create_memory_link",
        annotations={
            "title": "Create Memory Link",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_create_memory_link(params: CreateMemoryLinkInput) -> str:
        """Link a Pinecone vector to structured metadata.

        Bridges unstructured vector memories (Pinecone) with structured
        operational records (sessions, messages, files) for traceability.

        Args:
            params: CreateMemoryLinkInput with pinecone_vector_id and optional
                    summary, linked_agent_event, origin_file_or_source.

        Returns:
            Confirmation with new link_id.
        """
        session = get_db_session()
        try:
            record = MemoryLink(
                link_id=str(uuid.uuid4()),
                pinecone_vector_id=params.pinecone_vector_id,
                summary=params.summary,
                linked_agent_event=params.linked_agent_event,
                origin_file_or_source=params.origin_file_or_source,
            )
            session.add(record)
            session.commit()
            return f"Memory link created.\nLink ID: {record.link_id}\nPinecone ID: {params.pinecone_vector_id}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_create_memory_link error: {e}")
            return f"Error creating memory link: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_list_memory_links",
        annotations={
            "title": "List Memory Links",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_list_memory_links(params: ListMemoryLinksInput) -> str:
        """List memory links with optional filters.

        Args:
            params: ListMemoryLinksInput with optional pinecone_vector_id,
                    linked_agent_event, origin_file_or_source filters.

        Returns:
            JSON array of matching MemoryLink records, sorted newest first.
        """
        session = get_db_session()
        try:
            query = session.query(MemoryLink)
            if params.pinecone_vector_id:
                query = query.filter(MemoryLink.pinecone_vector_id == params.pinecone_vector_id)
            if params.linked_agent_event:
                query = query.filter(MemoryLink.linked_agent_event == params.linked_agent_event)
            if params.origin_file_or_source:
                query = query.filter(MemoryLink.origin_file_or_source.ilike(f"%{params.origin_file_or_source}%"))

            entries = query.order_by(MemoryLink.timestamp_added.desc()).all()
            if not entries:
                return "No memory links found matching your filters."
            return json.dumps([e.to_dict() for e in entries], indent=2)
        except Exception as e:
            logging.error(f"cmh_list_memory_links error: {e}")
            return f"Error listing memory links: {e}"
        finally:
            session.close()
