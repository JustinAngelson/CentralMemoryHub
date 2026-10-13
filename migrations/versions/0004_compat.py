"""Namespaced operational sessions/messages and principal-backed directory."""

from alembic import op

revision = "0004_compat"
down_revision = "0003_memory_kernel"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
      CREATE TABLE sessions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        principal_id uuid NOT NULL REFERENCES principals(id),
        user_principal_id uuid REFERENCES principals(id),
        namespace_id uuid NOT NULL REFERENCES namespaces(id),
        current_focus text, summary_notes text, active_context_tags text[],
        started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
        legacy_meta jsonb NOT NULL DEFAULT '{}'
      );
      CREATE TABLE messages (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        sender_principal_id uuid NOT NULL REFERENCES principals(id),
        receiver_principal_id uuid REFERENCES principals(id), receiver_text text,
        session_id uuid REFERENCES sessions(id),
        namespace_id uuid NOT NULL REFERENCES namespaces(id),
        message_type text NOT NULL, content text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(), legacy_meta jsonb NOT NULL DEFAULT '{}'
      );
      CREATE TABLE agent_directory (
        principal_id uuid PRIMARY KEY REFERENCES principals(id),
        description text, capabilities text[], reports_to_text text, seniority_level integer,
        aliases text[] NOT NULL DEFAULT '{}', legacy_meta jsonb NOT NULL DEFAULT '{}'
      );
      INSERT INTO agent_directory(principal_id) SELECT id FROM principals WHERE kind='agent';
      CREATE FUNCTION initialize_agent_directory() RETURNS trigger LANGUAGE plpgsql
        SECURITY DEFINER SET search_path=pg_catalog,public AS $$
        BEGIN
          IF NEW.kind='agent' THEN
            INSERT INTO public.agent_directory(principal_id) VALUES(NEW.id);
          END IF;
          RETURN NEW;
        END $$;
      REVOKE ALL ON FUNCTION initialize_agent_directory() FROM PUBLIC;
      CREATE TRIGGER initialize_agent_directory AFTER INSERT ON principals
        FOR EACH ROW EXECUTE FUNCTION initialize_agent_directory();
      CREATE INDEX sessions_namespace_principal ON sessions(namespace_id,principal_id,started_at);
      CREATE INDEX messages_namespace_session ON messages(namespace_id,session_id,created_at);
      ALTER TABLE memory_links ADD CONSTRAINT link_session
        FOREIGN KEY(linked_session_id) REFERENCES sessions(id);
      ALTER TABLE memory_links ADD CONSTRAINT link_message
        FOREIGN KEY(linked_message_id) REFERENCES messages(id);
      GRANT SELECT,INSERT,UPDATE,DELETE ON sessions,messages,agent_directory TO cmh_app;
    """)
    for table in ("sessions", "messages"):
        op.execute(f"""
          ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
          CREATE POLICY namespace_visibility ON {table} FOR ALL TO cmh_app
          USING(namespace_id=ANY(string_to_array(
            coalesce(current_setting('cmh.readable_namespaces',true),''),',')::uuid[]))
          WITH CHECK(namespace_id=ANY(string_to_array(
            coalesce(current_setting('cmh.readable_namespaces',true),''),',')::uuid[]));
        """)


def downgrade():
    op.execute("""
      ALTER TABLE memory_links DROP CONSTRAINT link_session;
      ALTER TABLE memory_links DROP CONSTRAINT link_message;
      DROP TRIGGER initialize_agent_directory ON principals;
      DROP FUNCTION initialize_agent_directory();
      DROP TABLE agent_directory,messages,sessions;
    """)
