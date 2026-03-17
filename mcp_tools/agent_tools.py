"""
Agent tools for the Central Memory Hub MCP Server.

15 tools covering agent directory (org chart), sessions, messages,
tasks, experiments, user insights, and system health.
"""
import json
import uuid
import logging
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

from mcp_tools import (
    get_db_session, pc, PINECONE_AVAILABLE,
    AgentDirectory, AgentSession, GPTMessage,
    AgentTask, Experiment, UserInsight,
)


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def build_hierarchy_tree(agent, agent_map: dict) -> dict:
    """Recursively build agent hierarchy from a flat agent map."""
    node = agent.to_dict()
    children = [
        build_hierarchy_tree(sub, agent_map)
        for sub in agent_map.values()
        if sub.reports_to == agent.agent_id
    ]
    node["subordinates"] = children
    return node


# ────────────────────────────────────────────────────────────────────
# Pydantic Input Models
# ────────────────────────────────────────────────────────────────────

class RegisterAgentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(..., min_length=1, description="Unique agent name")
    role: str = Field(..., min_length=1, description="Agent role or title")
    description: Optional[str] = Field(None, description="Agent description and purpose")
    capabilities: Optional[List[str]] = Field(None, description="List of agent capabilities")
    reports_to: Optional[str] = Field(None, description="agent_id of the supervising agent")
    seniority_level: Optional[int] = Field(None, ge=1, le=10, description="Seniority level 1-10")
    status: Optional[str] = Field("active", description="Status: active, inactive, or archived")


class CreateSessionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    agent_id: str = Field(..., min_length=1, description="agent_id from the agent directory")
    user_id: Optional[str] = Field(None, description="User ID if this is an interactive session")
    current_focus: Optional[str] = Field(None, description="Current task or focus area")
    summary_notes: Optional[str] = Field(None, description="Session notes or context")
    active_context_tags: Optional[List[str]] = Field(None, description="Active topic tags for this session")


class EndSessionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    session_id: str = Field(..., min_length=1, description="UUID of the session to end")


class ListSessionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    agent_id: Optional[str] = Field(None, description="Filter by agent_id")
    user_id: Optional[str] = Field(None, description="Filter by user_id")
    active_only: Optional[bool] = Field(False, description="If true, only return sessions without an ended_at timestamp")


class SendMessageInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    sender_agent: str = Field(..., min_length=1, description="Sending agent identifier")
    session_id: str = Field(..., min_length=1, description="Session UUID this message belongs to")
    content: str = Field(..., min_length=1, description="Message content")
    message_type: str = Field(..., description="Type: system, user, assistant, function, tool, or data")
    receiver_agent: Optional[str] = Field(None, description="Receiving agent identifier (optional)")


class CreateTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(..., min_length=1, description="Task title")
    assigned_to_agent: str = Field(..., min_length=1, description="Agent responsible for this task")
    created_by_agent: str = Field(..., min_length=1, description="Agent creating the task")
    status: str = Field(..., description="Status: pending, in_progress, completed, cancelled, or blocked")
    description: Optional[str] = Field(None, description="Detailed task description")
    priority: Optional[str] = Field(None, description="Priority: low, medium, high, or critical")
    linked_project: Optional[str] = Field(None, description="Associated project name")
    summary_notes: Optional[str] = Field(None, description="Additional notes")
    due_date: Optional[str] = Field(None, description="ISO date string for task due date")


class UpdateTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    task_id: str = Field(..., min_length=1, description="UUID of the task to update")
    status: Optional[str] = Field(None, description="New status")
    title: Optional[str] = Field(None, description="Updated title")
    assigned_to_agent: Optional[str] = Field(None, description="Reassign to this agent")
    priority: Optional[str] = Field(None, description="Updated priority")
    summary_notes: Optional[str] = Field(None, description="Updated notes")


class ListTasksInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    assigned_to_agent: Optional[str] = Field(None, description="Filter by assigned agent")
    created_by_agent: Optional[str] = Field(None, description="Filter by creating agent")
    status: Optional[str] = Field(None, description="Filter by status")
    linked_project: Optional[str] = Field(None, description="Filter by project name")


class CreateExperimentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(..., min_length=1, description="Experiment title")
    hypothesis: str = Field(..., min_length=1, description="What the experiment is testing")
    executing_agent: str = Field(..., min_length=1, description="Agent running the experiment")
    status: str = Field(..., description="Status: planned, running, complete, or failed")
    description: Optional[str] = Field(None, description="Experiment description and methodology")
    outcome: Optional[str] = Field(None, description="Observed outcome (fill in after completion)")
    notes: Optional[str] = Field(None, description="Additional notes or learnings")


class ListExperimentsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    status: Optional[str] = Field(None, description="Filter by status")
    executing_agent: Optional[str] = Field(None, description="Filter by executing agent")


class LogUserInsightInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    user_id: str = Field(..., min_length=1, description="User identifier")
    interaction_type: str = Field(..., min_length=1, description="Type: prompt, feedback, manual_override, etc.")
    summary: str = Field(..., min_length=1, description="Summary of the observed behavior or insight")
    related_agent_or_project: Optional[str] = Field(None, description="Associated agent or project")
    result: Optional[str] = Field(None, description="Outcome or response to the interaction")
    tone_tag: Optional[str] = Field(None, description="Tone: frustrated, in_flow, curious, satisfied, etc.")


class ListUserInsightsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    user_id: Optional[str] = Field(None, description="Filter by user ID")
    interaction_type: Optional[str] = Field(None, description="Filter by interaction type")
    tone_tag: Optional[str] = Field(None, description="Filter by tone tag")
    from_date: Optional[str] = Field(None, description="ISO date string — only return insights after this date")
    to_date: Optional[str] = Field(None, description="ISO date string — only return insights before this date")


# ────────────────────────────────────────────────────────────────────
# Tool Registrations
# ────────────────────────────────────────────────────────────────────

def register_agent_tools(mcp: FastMCP) -> None:
    """Register all agent tools with the MCP server."""

    @mcp.tool(
        name="cmh_list_agents",
        annotations={
            "title": "List Agent Directory (Org Chart)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_list_agents() -> str:
        """Get the full agent directory as a hierarchical org chart.

        Returns all agents organized by reporting relationships. Top-level agents
        (no reports_to) are roots; subordinates are nested under their managers.

        Returns:
            JSON org chart with nested subordinates at each level.
        """
        session = get_db_session()
        try:
            all_agents = session.query(AgentDirectory).all()
            if not all_agents:
                return "No agents registered in the directory."

            agent_map = {a.agent_id: a for a in all_agents}
            roots = [a for a in all_agents if not a.reports_to]
            hierarchy = [build_hierarchy_tree(a, agent_map) for a in roots]

            orphans = [
                a for a in all_agents
                if a.reports_to and a.reports_to not in agent_map
            ]
            if orphans:
                hierarchy.extend([a.to_dict() for a in orphans])

            return json.dumps(hierarchy, indent=2)
        except Exception as e:
            logging.error(f"cmh_list_agents error: {e}")
            return f"Error listing agents: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_register_agent",
        annotations={
            "title": "Register Agent",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_register_agent(params: RegisterAgentInput) -> str:
        """Add a new agent to the agent directory.

        Registers an agent with its role, capabilities, and reporting structure.
        Agent names must be unique across the directory.

        Args:
            params: RegisterAgentInput with name, role, and optional description,
                    capabilities, reports_to (agent_id), seniority_level, status.

        Returns:
            Confirmation with the new agent_id.
        """
        session = get_db_session()
        try:
            existing = session.query(AgentDirectory).filter_by(name=params.name).first()
            if existing:
                return f"Agent with name '{params.name}' already exists. agent_id: {existing.agent_id}"

            record = AgentDirectory(
                agent_id=str(uuid.uuid4()),
                name=params.name,
                role=params.role,
                description=params.description,
                capabilities=params.capabilities,
                reports_to=params.reports_to,
                seniority_level=params.seniority_level or 1,
                status=params.status or "active",
            )
            session.add(record)
            session.commit()
            return f"Agent registered.\nAgent ID: {record.agent_id}\nName: {params.name}\nRole: {params.role}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_register_agent error: {e}")
            return f"Error registering agent: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_create_session",
        annotations={
            "title": "Create Agent Session",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_create_session(params: CreateSessionInput) -> str:
        """Start a new agent session.

        Creates a session record for an agent, capturing what they're working on
        and any relevant context tags. Sessions are the containers for messages.

        Args:
            params: CreateSessionInput with agent_id and optional user_id,
                    current_focus, summary_notes, active_context_tags.

        Returns:
            Confirmation with the new session_id.
        """
        session = get_db_session()
        try:
            record = AgentSession(
                session_id=str(uuid.uuid4()),
                agent_id=params.agent_id,
                user_id=params.user_id,
                current_focus=params.current_focus,
                summary_notes=params.summary_notes,
                active_context_tags=params.active_context_tags,
            )
            session.add(record)
            session.commit()
            return f"Session created.\nSession ID: {record.session_id}\nAgent ID: {params.agent_id}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_create_session error: {e}")
            return f"Error creating session: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_end_session",
        annotations={
            "title": "End Agent Session",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_end_session(params: EndSessionInput) -> str:
        """End an agent session by recording the ended_at timestamp.

        Args:
            params: EndSessionInput with session_id.

        Returns:
            Confirmation with the session end time, or error if not found.
        """
        session = get_db_session()
        try:
            entry = session.query(AgentSession).get(params.session_id)
            if not entry:
                return f"Session not found: {params.session_id}"
            if entry.ended_at:
                return f"Session already ended at: {entry.ended_at.isoformat()}"

            entry.ended_at = datetime.utcnow()
            session.commit()
            return f"Session ended.\nSession ID: {params.session_id}\nEnded at: {entry.ended_at.isoformat()}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_end_session error: {e}")
            return f"Error ending session: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_list_sessions",
        annotations={
            "title": "List Agent Sessions",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_list_sessions(params: ListSessionsInput) -> str:
        """List agent sessions with optional filters.

        Args:
            params: ListSessionsInput with optional agent_id, user_id,
                    active_only (default False).

        Returns:
            JSON array of matching AgentSession records, sorted newest first.
        """
        session = get_db_session()
        try:
            query = session.query(AgentSession)
            if params.agent_id:
                query = query.filter(AgentSession.agent_id == params.agent_id)
            if params.user_id:
                query = query.filter(AgentSession.user_id == params.user_id)
            if params.active_only:
                query = query.filter(AgentSession.ended_at.is_(None))

            entries = query.order_by(AgentSession.started_at.desc()).all()
            if not entries:
                return "No sessions found matching your filters."
            return json.dumps([e.to_dict() for e in entries], indent=2)
        except Exception as e:
            logging.error(f"cmh_list_sessions error: {e}")
            return f"Error listing sessions: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_send_message",
        annotations={
            "title": "Send Inter-Agent Message",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_send_message(params: SendMessageInput) -> str:
        """Log an inter-agent message within a session.

        Records all communication between agents (or agent and user) for
        auditing, replay, and context reconstruction.

        Args:
            params: SendMessageInput with sender_agent, session_id, content,
                    message_type, and optional receiver_agent.

        Returns:
            Confirmation with new message_id.
        """
        session = get_db_session()
        try:
            record = GPTMessage(
                message_id=str(uuid.uuid4()),
                sender_agent=params.sender_agent,
                session_id=params.session_id,
                content=params.content,
                message_type=params.message_type,
                receiver_agent=params.receiver_agent,
            )
            session.add(record)
            session.commit()
            return f"Message logged.\nMessage ID: {record.message_id}\nFrom: {params.sender_agent} → {params.receiver_agent or 'broadcast'}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_send_message error: {e}")
            return f"Error logging message: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_create_task",
        annotations={
            "title": "Create Agent Task",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_create_task(params: CreateTaskInput) -> str:
        """Create and assign an agent task.

        Creates a structured task record with assignment, priority, and project
        linkage. Tasks are the primary unit of work tracking across agents.

        Args:
            params: CreateTaskInput with title, assigned_to_agent, created_by_agent,
                    status, and optional description, priority, linked_project,
                    summary_notes, due_date (ISO string).

        Returns:
            Confirmation with new task_id.
        """
        priority_map = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        session = get_db_session()
        try:
            priority_int = priority_map.get(params.priority.lower(), 2) if params.priority else None
            due = datetime.fromisoformat(params.due_date) if params.due_date else None

            record = AgentTask(
                task_id=str(uuid.uuid4()),
                title=params.title,
                assigned_to_agent=params.assigned_to_agent,
                created_by_agent=params.created_by_agent,
                status=params.status,
                description=params.description,
                priority=priority_int,
                linked_project=params.linked_project,
                summary_notes=params.summary_notes,
                due_date=due,
            )
            session.add(record)
            session.commit()
            return f"Task created.\nTask ID: {record.task_id}\nTitle: {params.title}\nAssigned to: {params.assigned_to_agent}\nStatus: {params.status}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_create_task error: {e}")
            return f"Error creating task: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_update_task",
        annotations={
            "title": "Update Agent Task",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_update_task(params: UpdateTaskInput) -> str:
        """Update task status, assignment, or details.

        Only provided fields are updated; omitted fields remain unchanged.

        Args:
            params: UpdateTaskInput with task_id and optional status, title,
                    assigned_to_agent, priority, summary_notes.

        Returns:
            Confirmation or error message.
        """
        priority_map = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        session = get_db_session()
        try:
            entry = session.query(AgentTask).get(params.task_id)
            if not entry:
                return f"Task not found: {params.task_id}"

            if params.status is not None:
                entry.status = params.status
            if params.title is not None:
                entry.title = params.title
            if params.assigned_to_agent is not None:
                entry.assigned_to_agent = params.assigned_to_agent
            if params.priority is not None:
                entry.priority = priority_map.get(params.priority.lower(), entry.priority)
            if params.summary_notes is not None:
                entry.summary_notes = params.summary_notes

            session.commit()
            return f"Task updated.\nTask ID: {params.task_id}\nTitle: {entry.title}\nStatus: {entry.status}\nAssigned to: {entry.assigned_to_agent}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_update_task error: {e}")
            return f"Error updating task: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_list_tasks",
        annotations={
            "title": "List Agent Tasks",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_list_tasks(params: ListTasksInput) -> str:
        """List agent tasks with optional filters.

        Args:
            params: ListTasksInput with optional assigned_to_agent,
                    created_by_agent, status, linked_project filters.

        Returns:
            JSON array of matching AgentTask records, sorted by creation date descending.
        """
        session = get_db_session()
        try:
            query = session.query(AgentTask)
            if params.assigned_to_agent:
                query = query.filter(AgentTask.assigned_to_agent == params.assigned_to_agent)
            if params.created_by_agent:
                query = query.filter(AgentTask.created_by_agent == params.created_by_agent)
            if params.status:
                query = query.filter(AgentTask.status == params.status)
            if params.linked_project:
                query = query.filter(AgentTask.linked_project == params.linked_project)

            entries = query.order_by(AgentTask.created_at.desc()).all()
            if not entries:
                return "No tasks found matching your filters."
            return json.dumps([e.to_dict() for e in entries], indent=2)
        except Exception as e:
            logging.error(f"cmh_list_tasks error: {e}")
            return f"Error listing tasks: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_create_experiment",
        annotations={
            "title": "Create Experiment",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_create_experiment(params: CreateExperimentInput) -> str:
        """Track an agent experiment with hypothesis, methodology, and outcomes.

        Use to run structured trials — A/B tests, prompt experiments, workflow
        comparisons, or any testable hypothesis about agent behavior or performance.

        Args:
            params: CreateExperimentInput with title, hypothesis, executing_agent,
                    status, and optional description, outcome, notes.

        Returns:
            Confirmation with new experiment_id.
        """
        session = get_db_session()
        try:
            record = Experiment(
                experiment_id=str(uuid.uuid4()),
                title=params.title,
                hypothesis=params.hypothesis,
                executing_agent=params.executing_agent,
                status=params.status,
                description=params.description,
                outcome=params.outcome,
                notes=params.notes,
            )
            session.add(record)
            session.commit()
            return f"Experiment created.\nExperiment ID: {record.experiment_id}\nTitle: {params.title}\nStatus: {params.status}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_create_experiment error: {e}")
            return f"Error creating experiment: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_list_experiments",
        annotations={
            "title": "List Experiments",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_list_experiments(params: ListExperimentsInput) -> str:
        """List experiments with optional filters.

        Args:
            params: ListExperimentsInput with optional status and executing_agent filters.

        Returns:
            JSON array of matching Experiment records, sorted newest first.
        """
        session = get_db_session()
        try:
            query = session.query(Experiment)
            if params.status:
                query = query.filter(Experiment.status == params.status)
            if params.executing_agent:
                query = query.filter(Experiment.executing_agent == params.executing_agent)

            entries = query.order_by(Experiment.created_at.desc()).all()
            if not entries:
                return "No experiments found matching your filters."
            return json.dumps([e.to_dict() for e in entries], indent=2)
        except Exception as e:
            logging.error(f"cmh_list_experiments error: {e}")
            return f"Error listing experiments: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_log_user_insight",
        annotations={
            "title": "Log User Insight",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_log_user_insight(params: LogUserInsightInput) -> str:
        """Record a user behavior insight or preference observation.

        Captures patterns in how users interact with agents — what prompts
        they use, how they react, their preferred communication styles —
        so agents can adapt over time.

        Args:
            params: LogUserInsightInput with user_id, interaction_type, summary,
                    and optional related_agent_or_project, result, tone_tag.

        Returns:
            Confirmation with new insight_id.
        """
        session = get_db_session()
        try:
            record = UserInsight(
                insight_id=str(uuid.uuid4()),
                user_id=params.user_id,
                interaction_type=params.interaction_type,
                summary=params.summary,
                related_agent_or_project=params.related_agent_or_project,
                result=params.result,
                tone_tag=params.tone_tag,
            )
            session.add(record)
            session.commit()
            return f"User insight logged.\nInsight ID: {record.insight_id}\nUser: {params.user_id}\nType: {params.interaction_type}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_log_user_insight error: {e}")
            return f"Error logging user insight: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_list_user_insights",
        annotations={
            "title": "List User Insights",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_list_user_insights(params: ListUserInsightsInput) -> str:
        """List user insights with optional filters.

        Args:
            params: ListUserInsightsInput with optional user_id, interaction_type,
                    tone_tag, from_date, to_date (ISO strings).

        Returns:
            JSON array of matching UserInsight records, sorted newest first.
        """
        session = get_db_session()
        try:
            query = session.query(UserInsight)
            if params.user_id:
                query = query.filter(UserInsight.user_id == params.user_id)
            if params.interaction_type:
                query = query.filter(UserInsight.interaction_type == params.interaction_type)
            if params.tone_tag:
                query = query.filter(UserInsight.tone_tag == params.tone_tag)
            if params.from_date:
                query = query.filter(UserInsight.timestamp >= datetime.fromisoformat(params.from_date))
            if params.to_date:
                query = query.filter(UserInsight.timestamp <= datetime.fromisoformat(params.to_date))

            entries = query.order_by(UserInsight.timestamp.desc()).all()
            if not entries:
                return "No user insights found matching your filters."
            return json.dumps([e.to_dict() for e in entries], indent=2)
        except Exception as e:
            logging.error(f"cmh_list_user_insights error: {e}")
            return f"Error listing user insights: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_health_check",
        annotations={
            "title": "CMH Health Check",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def cmh_health_check() -> str:
        """Check CMH database and Pinecone connectivity.

        Runs a lightweight query against the database and checks Pinecone
        index stats to confirm all backend systems are operational.

        Returns:
            JSON status object with database and Pinecone health indicators.
        """
        status = {
            "database": "unknown",
            "pinecone": "unknown",
            "agent_count": 0,
            "memory_count": 0,
        }

        session = get_db_session()
        try:
            from mcp_tools import UnstructuredData
            agent_count = session.query(AgentDirectory).count()
            memory_count = session.query(UnstructuredData).count()
            status["database"] = "ok"
            status["agent_count"] = agent_count
            status["memory_count"] = memory_count
        except Exception as e:
            status["database"] = f"error: {e}"
        finally:
            session.close()

        if PINECONE_AVAILABLE and pc:
            try:
                stats = pc.get_index_stats()
                status["pinecone"] = "ok"
                status["pinecone_stats"] = stats
            except Exception as e:
                status["pinecone"] = f"error: {e}"
        else:
            status["pinecone"] = "unavailable (client not loaded)"

        return json.dumps(status, indent=2)
