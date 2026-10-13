"""Explicit namespace/kind filters plus RLS, graph reachability and RRF k=60."""

from typing import Protocol

from sqlalchemy import text

from cmh.services.entities import encode, public_snapshot


class VectorStore(Protocol):
    def top(self, connection, candidates, params, vector, limit): ...


class PgVectorStore:
    def top(self, connection, candidates, params, vector, limit):
        return connection.execute(text(candidates + """
          SELECT id,snapshot FROM candidates
          WHERE vector IS NOT NULL
          ORDER BY vector <=> CAST(:vector AS vector),id LIMIT :top
        """), {**params, "vector": encode(vector), "top": limit}).mappings().all()


def graph(connection, readable, kinds, anchor, depth, at, historical=False):
    rows = connection.execute(text("""
      WITH RECURSIVE walk(id,depth,path) AS (
        SELECT id,0,ARRAY[id] FROM entities
        WHERE id=:anchor AND namespace_id=ANY(CAST(:readable AS uuid[]))
          AND kind=ANY(CAST(:graph_kinds AS text[]))
        UNION ALL
        SELECT node.id,walk.depth+1,walk.path||node.id FROM walk
          JOIN edges edge ON edge.src_entity_id=walk.id OR edge.dst_entity_id=walk.id
          JOIN entities node ON node.id=CASE WHEN edge.src_entity_id=walk.id
            THEN edge.dst_entity_id ELSE edge.src_entity_id END
        WHERE walk.depth<:depth AND (edge.status='active' OR :historical)
          AND edge.valid_from<=:at AND (edge.valid_to IS NULL OR edge.valid_to>:at)
          AND node.namespace_id=ANY(CAST(:readable AS uuid[]))
          AND node.kind=ANY(CAST(:graph_kinds AS text[]))
          AND NOT node.id=ANY(walk.path)
      ) SELECT DISTINCT id FROM walk
    """), {"anchor": anchor, "readable": readable, "graph_kinds": kinds,
           "depth": depth, "at": at, "historical": historical}).scalars().all()
    return [str(identity) for identity in rows]


def hybrid(connection, readable, kinds, query, provider, vector_store, *,
           namespace_id=None, candidate_ids=None, as_of=None, limit=10):
    from cmh.services.embedding import EmbeddingUnavailable

    params = {
        "readable": readable, "kinds": kinds, "namespace": namespace_id,
        "anchor_filter": candidate_ids is not None, "candidates": candidate_ids or [],
        "at": as_of, "query": query, "model": provider.model,
    }
    historical = as_of is not None
    # Current retrieval uses the indexed TSV and vector. Historical queries use
    # immutable snapshot text and its v2 vector, never the mutable current vector.
    tsv = ("to_tsvector('english',coalesce(v.snapshot->>'title','')||' '||"
           "coalesce(v.snapshot->>'search_text',''))") if historical else "e.search_tsv"
    vector = ("CASE WHEN v.snapshot->>'__embedding_model'=:model THEN "
              "CAST(v.snapshot->>'__embedding' AS vector) END") if historical else "b.embedding"
    candidates = f"""
      WITH candidates AS (
        SELECT e.id,v.snapshot,{tsv} AS tsv,{vector} AS vector FROM entities e
        JOIN LATERAL (
          SELECT snapshot,version FROM entity_versions
          WHERE entity_id=e.id AND
            ((CAST(:at AS timestamptz) IS NULL AND version=e.current_version) OR
             changed_at<=CAST(:at AS timestamptz))
          ORDER BY version DESC LIMIT 1
        ) v ON true
        LEFT JOIN embeddings b ON b.entity_id=e.id AND b.entity_version=v.version AND b.model=:model
        WHERE e.namespace_id=ANY(CAST(:readable AS uuid[]))
          AND e.kind=ANY(CAST(:kinds AS text[]))
          AND v.snapshot->>'status'='canonical'
          AND (CAST(:namespace AS uuid) IS NULL OR e.namespace_id=CAST(:namespace AS uuid))
          AND (:anchor_filter=false OR e.id=ANY(CAST(:candidates AS uuid[])))
      )
    """
    top = max(limit, 50)
    fulltext = connection.execute(text(candidates + """
      SELECT id,snapshot FROM candidates WHERE tsv @@ plainto_tsquery('english',:query)
      ORDER BY ts_rank(tsv,plainto_tsquery('english',:query)) DESC,id LIMIT :top
    """), {**params, "top": top}).mappings().all()
    degraded = False
    try:
        vector_results = vector_store.top(connection, candidates, params, provider.embed(query), top)
    except EmbeddingUnavailable:
        degraded = True
        vector_results = []
    scores, snapshots = {}, {}
    for ranked in (vector_results, fulltext):
        for rank, row in enumerate(ranked, 1):
            identity = str(row["id"])
            scores[identity] = scores.get(identity, 0) + 1 / (60 + rank)
            snapshots[identity] = row["snapshot"]
    ordered = sorted(scores, key=lambda identity: (-scores[identity], identity))[:limit]
    results = []
    for identity in ordered:
        snapshot = public_snapshot(snapshots[identity])
        snapshot.update(
            id=identity, similarity_score=scores[identity],
            content=snapshot.get("content") or snapshot.get("body") or snapshot.get("search_text", ""),
            pinecone_id=snapshot.get("legacy_meta", {}).get("pinecone_id"),
        )
        results.append(snapshot)
    return {"results": results, "degraded": degraded}
