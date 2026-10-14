"""Import kinds, namespaced skill assignments, safe waitlist and run bookkeeping."""
from alembic import op

from cmh.kernel import TYPED

revision = "0005_import"
down_revision = "0004_compat"
branch_labels = None
depends_on = None


def integrity(registry):
    cases = " ".join(f"WHEN '{kind}' THEN '{table}'" for kind, (table, _) in registry.items())
    unions = " UNION ALL ".join(f"SELECT id FROM public.{table} WHERE id=target"
                               for table, _ in registry.values())
    op.execute(f"""
      CREATE OR REPLACE FUNCTION kernel_integrity(target uuid) RETURNS void
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
          RAISE EXCEPTION 'Missing current entity version'; END IF;
        IF item.kind='memory_link' AND
          (SELECT count(*) FROM public.edges e JOIN public.entities dst ON dst.id=e.dst_entity_id
           WHERE e.src_entity_id=target AND e.type='about' AND dst.kind='memory')<>1 THEN
          RAISE EXCEPTION 'Memory link requires exactly one about memory edge'; END IF;
      END $$;
      REVOKE ALL ON FUNCTION kernel_integrity(uuid) FROM PUBLIC;
    """)


def upgrade():
    op.execute("SET LOCAL ROLE cmh_migrate")
    for kind in ("skill", "resource"):
        table, columns = TYPED[kind]
        fields = ",".join(f"{key} {value}" for key, value in columns.items())
        op.execute(f"""
          CREATE TABLE {table}(id uuid PRIMARY KEY REFERENCES entities(id),{fields});
          GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO cmh_app;
          ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
          CREATE POLICY readable ON {table}
            USING(EXISTS(SELECT 1 FROM entities e WHERE e.id={table}.id))
            WITH CHECK(EXISTS(SELECT 1 FROM entities e WHERE e.id={table}.id));
          CREATE CONSTRAINT TRIGGER typed_integrity AFTER INSERT OR UPDATE OR DELETE ON {table}
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_kernel_integrity();
        """)
    integrity(TYPED)
    op.execute("""
      ALTER TABLE sessions ALTER COLUMN principal_id DROP NOT NULL;
      ALTER TABLE messages ALTER COLUMN sender_principal_id DROP NOT NULL;
      CREATE UNIQUE INDEX single_bootstrap_owner ON principals ((role)) WHERE role='owner';
      CREATE TABLE principal_skill_assignments(
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), principal_id uuid NOT NULL REFERENCES principals,
        skill_entity_id uuid NOT NULL REFERENCES skills(id),
        namespace_id uuid NOT NULL REFERENCES namespaces, proficiency text,
        legacy_meta jsonb NOT NULL DEFAULT '{}', UNIQUE(principal_id,skill_entity_id));
      ALTER TABLE principal_skill_assignments ENABLE ROW LEVEL SECURITY;
      CREATE POLICY readable ON principal_skill_assignments
        USING(namespace_id=ANY(string_to_array(coalesce(
          current_setting('cmh.readable_namespaces',true),''),',')::uuid[]))
        WITH CHECK(namespace_id=ANY(string_to_array(coalesce(
          current_setting('cmh.readable_namespaces',true),''),',')::uuid[])
          AND EXISTS(SELECT 1 FROM entities e WHERE e.id=skill_entity_id
                     AND e.namespace_id=principal_skill_assignments.namespace_id AND e.kind='skill'));
      CREATE TABLE waitlist(
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),email varchar(120) NOT NULL,
        first_name varchar(100),company varchar(200),role varchar(100),
        created_at timestamptz NOT NULL DEFAULT now(),source text NOT NULL,
        legacy_meta jsonb NOT NULL DEFAULT '{}');
      CREATE UNIQUE INDEX waitlist_lower_email ON waitlist(lower(email));
      CREATE TABLE waitlist_attempts(ip_hash text NOT NULL,attempted_at timestamptz NOT NULL);
      CREATE INDEX waitlist_attempts_ip_time ON waitlist_attempts(ip_hash,attempted_at);
      CREATE TABLE import_runs(
        id uuid PRIMARY KEY,mode text NOT NULL,checksums jsonb NOT NULL,
        started_at timestamptz NOT NULL,finished_at timestamptz,counts jsonb NOT NULL DEFAULT '{}');
      CREATE UNIQUE INDEX sessions_v1_identity ON sessions(
        (legacy_meta->>'v1_table'),(legacy_meta->>'v1_id')) WHERE legacy_meta ? 'v1_id';
      CREATE UNIQUE INDEX messages_v1_identity ON messages(
        (legacy_meta->>'v1_table'),(legacy_meta->>'v1_id')) WHERE legacy_meta ? 'v1_id';
      CREATE UNIQUE INDEX assignments_v1_identity ON principal_skill_assignments(
        (legacy_meta->>'v1_table'),(legacy_meta->>'v1_id')) WHERE legacy_meta ? 'v1_id';
      GRANT SELECT,INSERT,UPDATE,DELETE ON
        principal_skill_assignments,waitlist,waitlist_attempts,import_runs TO cmh_app;
      RESET ROLE;
    """)


def downgrade():
    op.execute("SET LOCAL ROLE cmh_migrate")
    op.execute("""
      DROP INDEX IF EXISTS sessions_v1_identity,messages_v1_identity;
      ALTER TABLE sessions ALTER COLUMN principal_id SET NOT NULL;
      ALTER TABLE messages ALTER COLUMN sender_principal_id SET NOT NULL;
      DROP TABLE import_runs,waitlist_attempts,waitlist,principal_skill_assignments;
      ALTER TABLE principals DROP CONSTRAINT IF EXISTS human_tiers;
      DROP INDEX single_bootstrap_owner;
    """)
    integrity({k: v for k, v in TYPED.items() if k not in {"skill", "resource"}})
    op.execute("DROP TABLE resources,skills")
    op.execute("RESET ROLE")
