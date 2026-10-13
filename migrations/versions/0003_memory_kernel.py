"""Native memory kernel; immutable versions, typed integrity and fail-closed RLS."""

from alembic import op

from cmh.kernel import TYPED as CURRENT_TYPED

# Freeze this historical revision; later registries must not create their
# tables before their own migration or break revision-0003 round trips.
TYPED = {kind: value for kind, value in CURRENT_TYPED.items() if kind not in {"skill", "resource"}}

revision = "0003_memory_kernel"
down_revision = "0002_identity"
branch_labels = None
depends_on = None

TABLES = ["entities", "entity_versions", "edge_types", "edges", "embeddings"]
TABLES += [table for table, _ in TYPED.values()]


def upgrade():
    op.execute("SET LOCAL ROLE cmh_migrate")
    op.execute("""
      CREATE TABLE entities (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), kind text NOT NULL,
        namespace_id uuid NOT NULL REFERENCES namespaces(id),
        status text NOT NULL DEFAULT 'canonical' CHECK(status IN
          ('proposed','canonical','stale','superseded','withdrawn','retired','tombstoned')),
        title text, search_text text NOT NULL DEFAULT '',
        search_tsv tsvector GENERATED ALWAYS AS
          (to_tsvector('english',coalesce(title,'') || ' ' || search_text)) STORED,
        author_principal_id uuid REFERENCES principals(id), actor text NOT NULL,
        source_type text NOT NULL, source_ref text,
        confidence numeric(3,2) NOT NULL CHECK(confidence BETWEEN 0 AND 1),
        occurred_at timestamptz NOT NULL,
        supersedes_id uuid REFERENCES entities(id), superseded_by_id uuid REFERENCES entities(id),
        source_system text, source_id text, source_modified_at timestamptz, synced_at timestamptz,
        current_version integer NOT NULL DEFAULT 1 CHECK(current_version>0),
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
        legacy_meta jsonb NOT NULL DEFAULT '{}', UNIQUE(source_system,source_id)
      );
      CREATE TABLE entity_versions (
        entity_id uuid REFERENCES entities(id), version integer CHECK(version>0),
        snapshot jsonb NOT NULL, status text NOT NULL, change_kind text NOT NULL,
        changed_by uuid REFERENCES principals(id), actor text NOT NULL,
        changed_at timestamptz NOT NULL, PRIMARY KEY(entity_id,version)
      );
      CREATE TABLE edge_types (
        type text PRIMARY KEY, allowed_src_kinds text[] NOT NULL,
        allowed_dst_kinds text[] NOT NULL, mirrored boolean NOT NULL, description text
      );
      CREATE TABLE edges (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), src_entity_id uuid NOT NULL REFERENCES entities,
        dst_entity_id uuid NOT NULL REFERENCES entities, type text NOT NULL REFERENCES edge_types,
        author_principal_id uuid REFERENCES principals, actor text NOT NULL,
        source_type text, source_ref text, confidence numeric(3,2) CHECK(confidence BETWEEN 0 AND 1),
        valid_from timestamptz NOT NULL DEFAULT now(), valid_to timestamptz,
        status text NOT NULL CHECK(status IN ('active','retired')),
        created_at timestamptz NOT NULL DEFAULT now()
      );
      CREATE TABLE embeddings (
        entity_id uuid REFERENCES entities, model text NOT NULL, entity_version integer NOT NULL,
        embedding vector(1536) NOT NULL, created_at timestamptz NOT NULL,
        PRIMARY KEY(entity_id,model),
        FOREIGN KEY(entity_id,entity_version) REFERENCES entity_versions(entity_id,version)
      );
      CREATE INDEX entities_namespace_kind_status ON entities(namespace_id,kind,status);
      CREATE INDEX entities_author_time ON entities(author_principal_id,occurred_at);
      CREATE INDEX entities_search ON entities USING gin(search_tsv);
      CREATE UNIQUE INDEX entities_v1_identity ON entities
        ((legacy_meta->>'v1_table'),(legacy_meta->>'v1_id'))
        WHERE legacy_meta ? 'v1_table' AND legacy_meta ? 'v1_id';
      CREATE INDEX entities_legacy_meta ON entities USING gin(legacy_meta);
      CREATE INDEX versions_as_of ON entity_versions(entity_id,changed_at DESC,version DESC);
      CREATE INDEX edges_source_type ON edges(src_entity_id,type,status);
      CREATE INDEX edges_destination_type ON edges(dst_entity_id,type,status);
      CREATE INDEX embeddings_cosine ON embeddings USING hnsw(embedding vector_cosine_ops);
    """)
    for table, columns in TYPED.values():
        fields = ",".join(f"{name} {definition}" for name, definition in columns.items())
        op.execute(f"CREATE TABLE {table} (id uuid PRIMARY KEY REFERENCES entities(id),{fields})")
    # The deferrable constraint checks final transaction state, not insertion order.
    cases = " ".join(f"WHEN '{kind}' THEN '{table}'" for kind, (table, _) in TYPED.items())
    unions = " UNION ALL ".join(f"SELECT id FROM {table} WHERE id=target" for table, _ in TYPED.values())
    op.execute(f"""
      CREATE FUNCTION kernel_integrity(target uuid) RETURNS void
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE item record; typed_table text; matching boolean; total integer;
      BEGIN
        SELECT * INTO item FROM public.entities WHERE id=target;
        IF NOT FOUND THEN RETURN; END IF;
        typed_table := CASE item.kind {cases} ELSE NULL END;
        IF typed_table IS NULL THEN RAISE EXCEPTION 'Unsupported kernel kind'; END IF;
        EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I WHERE id=$1)',typed_table)
          INTO matching USING target;
        SELECT count(*) INTO total FROM ({unions}) all_typed;
        IF NOT matching OR total<>1 THEN RAISE EXCEPTION 'Typed registry mismatch'; END IF;
        IF NOT EXISTS(SELECT 1 FROM public.entity_versions
          WHERE entity_id=target AND version=item.current_version) THEN
          RAISE EXCEPTION 'Missing current entity version';
        END IF;
        IF item.kind='memory_link' AND
          (SELECT count(*) FROM public.edges e JOIN public.entities dst ON dst.id=e.dst_entity_id
           WHERE e.src_entity_id=target AND e.type='about' AND dst.kind='memory')<>1 THEN
          RAISE EXCEPTION 'Memory link requires exactly one about memory edge';
        END IF;
      END $$;
      REVOKE ALL ON FUNCTION kernel_integrity(uuid) FROM PUBLIC;
      CREATE FUNCTION check_kernel_integrity() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      BEGIN
        PERFORM public.kernel_integrity(CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END);
        RETURN NULL;
      END $$;
    """)
    for table in ["entities", *[name for name, _ in TYPED.values()]]:
        op.execute(f"""
          CREATE CONSTRAINT TRIGGER typed_integrity AFTER INSERT OR UPDATE OR DELETE ON {table}
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_kernel_integrity()
        """)
    op.execute("""
      CREATE FUNCTION check_kernel_edge() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE src_kind text; dst_kind text; vocabulary record;
      BEGIN
        IF TG_OP<>'DELETE' THEN
          SELECT kind INTO src_kind FROM public.entities WHERE id=NEW.src_entity_id;
          SELECT kind INTO dst_kind FROM public.entities WHERE id=NEW.dst_entity_id;
          SELECT * INTO vocabulary FROM public.edge_types WHERE type=NEW.type;
          IF NOT(src_kind=ANY(vocabulary.allowed_src_kinds))
            OR NOT(dst_kind=ANY(vocabulary.allowed_dst_kinds)) THEN
            RAISE EXCEPTION 'Edge endpoint kind mismatch';
          END IF;
          PERFORM public.kernel_integrity(NEW.src_entity_id);
        END IF;
        IF TG_OP<>'INSERT' THEN PERFORM public.kernel_integrity(OLD.src_entity_id); END IF;
        RETURN NULL;
      END $$;
      CREATE CONSTRAINT TRIGGER edge_integrity AFTER INSERT OR UPDATE OR DELETE ON edges
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_kernel_edge();
    """)
    readable = ("namespace_id::text=ANY(string_to_array(coalesce("
                "current_setting('cmh.readable_namespaces',true),''),','))")
    for table in TABLES:
        permissions = "SELECT,INSERT" if table == "entity_versions" else "SELECT,INSERT,UPDATE,DELETE"
        op.execute(f"GRANT {permissions} ON {table} TO cmh_app")
        if table == "edge_types":
            continue
        condition = readable if table == "entities" else (
            "EXISTS(SELECT 1 FROM entities e WHERE e.id="
            + (f"{table}.id)" if table in [name for name, _ in TYPED.values()]
               else f"{table}.entity_id)")
        )
        if table == "edges":
            condition = (
                "EXISTS(SELECT 1 FROM entities e WHERE e.id=edges.src_entity_id) AND "
                "EXISTS(SELECT 1 FROM entities e WHERE e.id=edges.dst_entity_id)"
            )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY readable ON {table} USING ({condition}) WITH CHECK ({condition})")
    op.execute("RESET ROLE")


def downgrade():
    op.execute("SET LOCAL ROLE cmh_migrate")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table} CASCADE")
    for function in ("check_kernel_edge()", "check_kernel_integrity()", "kernel_integrity(uuid)"):
        op.execute(f"DROP FUNCTION {function}")
    op.execute("RESET ROLE")
