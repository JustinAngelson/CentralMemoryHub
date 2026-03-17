"""
Memory tools for the Central Memory Hub MCP Server.

Core tools for cross-agent organizational memory: semantic search,
store, and retrieve for both unstructured and structured memories.
"""
import json
import uuid
import logging
from typing import List
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

from mcp_tools import get_db_session, UnstructuredData, ProjectDecision, pc, PINECONE_AVAILABLE


class SearchMemoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., min_length=1, max_length=1000, description="Natural-language search query")


class StoreMemoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    content: str = Field(..., min_length=1, max_length=10000, description="Content to store in organizational memory")


class GetMemoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    id: str = Field(..., min_length=1, description="UUID of the memory entry")


class StoreStructuredInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    gpt_role: str = Field(..., min_length=1, description="Role of the agent storing this memory")
    decision_text: str = Field(..., min_length=1, description="Decision or information content")
    context_embedding: List[float] = Field(..., description="Pre-computed vector embedding")
    related_documents: List[str] = Field(..., description="IDs of related documents or memories")


def register_memory_tools(mcp: FastMCP) -> None:
    """Register all memory tools with the MCP server."""

    @mcp.tool(
        name="cmh_search_memory",
        annotations={
            "title": "Search Memory",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_search_memory(params: SearchMemoryInput) -> str:
        """Search the Central Memory Hub using semantic similarity (Pinecone vector search).

        This is the primary retrieval tool. Takes a natural-language query and returns
        the most relevant stored memories ranked by similarity score.

        Args:
            params: SearchMemoryInput with:
                - query (str): Natural-language search query (1-1000 chars)

        Returns:
            Formatted results with score, ID, and content for each match.

        Examples:
            - "What decisions were made about the Starnet engagement?"
            - "Nix session bridge architecture"
            - "Designer Decor Direct B2B pivot strategy"
        """
        if not PINECONE_AVAILABLE:
            return "Error: Pinecone client not available. Vector search is offline."

        session = get_db_session()
        try:
            pinecone_results = pc.search_by_content(params.query)
            pinecone_ids = [match["id"] for match in pinecone_results]

            if not pinecone_ids:
                return f'No memories found matching: "{params.query}"'

            entries = (
                session.query(UnstructuredData)
                .filter(UnstructuredData.pinecone_id.in_(pinecone_ids))
                .all()
            )

            results = []
            for entry in entries:
                score = 0.0
                for match in pinecone_results:
                    if entry.pinecone_id == match["id"]:
                        score = match["score"]
                        break
                results.append({
                    "id": entry.id,
                    "content": entry.content,
                    "pinecone_id": entry.pinecone_id,
                    "similarity_score": score,
                })

            results.sort(key=lambda x: x["similarity_score"], reverse=True)

            formatted = "\n\n---\n\n".join(
                f'[{i+1}] (score: {r["similarity_score"]:.3f}) [id: {r["id"]}]\n{r["content"]}'
                for i, r in enumerate(results)
            )
            return f'Found {len(results)} result(s) for "{params.query}":\n\n{formatted}'

        except Exception as e:
            logging.error(f"cmh_search_memory error: {e}")
            return f"Error searching memory: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_store_memory",
        annotations={
            "title": "Store Memory",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_store_memory(params: StoreMemoryInput) -> str:
        """Store unstructured content in the Central Memory Hub with automatic Pinecone embedding.

        Use for any information that should persist across sessions and be retrievable
        by any agent: decisions, context, notes, session summaries, relationship milestones,
        patterns, or any organizational knowledge.

        Best practices — include metadata tags for better retrieval:
            [source: direct|reconstructed|consolidated|reported|inferred]
            [type: state|episode|pattern|fact|relationship]
            [agent: nix|claude|jr|tt|justin]

        Keep entries focused — one concept or decision per entry for better retrieval.

        Args:
            params: StoreMemoryInput with:
                - content (str): Content to store (1-10000 chars)

        Returns:
            Confirmation with database ID and Pinecone vector ID.
        """
        if not PINECONE_AVAILABLE:
            return "Error: Pinecone client not available. Cannot embed and store."

        session = get_db_session()
        try:
            embedding, pinecone_id = pc.process_unstructured_data(params.content)

            record = UnstructuredData(
                id=str(uuid.uuid4()),
                content=params.content,
                pinecone_id=pinecone_id,
            )
            session.add(record)
            session.commit()

            return f"Memory stored successfully.\nID: {record.id}\nPinecone ID: {pinecone_id}"

        except Exception as e:
            session.rollback()
            logging.error(f"cmh_store_memory error: {e}")
            return f"Error storing memory: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_get_memory",
        annotations={
            "title": "Get Memory by ID",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_get_memory(params: GetMemoryInput) -> str:
        """Retrieve a specific unstructured memory entry by its UUID.

        Args:
            params: GetMemoryInput with:
                - id (str): UUID of the memory to retrieve

        Returns:
            JSON with { id, content, pinecone_id } or error message.
        """
        session = get_db_session()
        try:
            entry = session.query(UnstructuredData).get(params.id)
            if not entry:
                return f"Memory not found: {params.id}"
            return json.dumps(entry.to_dict(), indent=2)
        except Exception as e:
            logging.error(f"cmh_get_memory error: {e}")
            return f"Error retrieving memory: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_store_structured",
        annotations={
            "title": "Store Structured Memory",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def cmh_store_structured(params: StoreStructuredInput) -> str:
        """Store structured memory with role attribution and document links.

        Use for formal decisions that need explicit role context and document
        cross-references. Note: context_embedding must be provided (the CMH
        does not auto-embed structured entries).

        Args:
            params: StoreStructuredInput with:
                - gpt_role (str): Role of the agent (e.g., "chief_of_staff")
                - decision_text (str): The decision content
                - context_embedding (List[float]): Pre-computed vector
                - related_documents (List[str]): Related document IDs

        Returns:
            Confirmation with database ID.
        """
        session = get_db_session()
        try:
            record = ProjectDecision(
                id=str(uuid.uuid4()),
                gpt_role=params.gpt_role,
                decision_text=params.decision_text,
                context_embedding=params.context_embedding,
                related_documents=params.related_documents,
            )
            session.add(record)
            session.commit()
            return f"Structured memory stored.\nID: {record.id}"
        except Exception as e:
            session.rollback()
            logging.error(f"cmh_store_structured error: {e}")
            return f"Error storing structured memory: {e}"
        finally:
            session.close()

    @mcp.tool(
        name="cmh_get_structured",
        annotations={
            "title": "Get Structured Memory by ID",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def cmh_get_structured(params: GetMemoryInput) -> str:
        """Retrieve a specific structured memory entry by its UUID.

        Args:
            params: GetMemoryInput with:
                - id (str): UUID of the structured memory

        Returns:
            JSON with { id, gpt_role, decision_text, context_embedding,
            related_documents, timestamp } or error message.
        """
        session = get_db_session()
        try:
            entry = session.query(ProjectDecision).get(params.id)
            if not entry:
                return f"Structured memory not found: {params.id}"
            return json.dumps(entry.to_dict(), indent=2)
        except Exception as e:
            logging.error(f"cmh_get_structured error: {e}")
            return f"Error retrieving structured memory: {e}"
        finally:
            session.close()
