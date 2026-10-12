"""Identity and append-only audit perimeter; no record or OAuth tables."""

from alembic import op

revision = "0002_identity"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = (
    "principals", "users", "admin_sessions", "credential_templates", "credentials",
    "namespaces", "namespace_grants", "approvals", "notifications", "bootstrap_state",
    "audit_events",
)


def upgrade():
    # Tests migrate with an administrative connection; ownership is still the
    # migration role. In development the connection already logs in as that role.
    op.execute("SET LOCAL ROLE cmh_migrate")
    op.execute("""
    CREATE TABLE principals (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      kind text NOT NULL CHECK(kind IN ('human','agent','service')),
      slug text UNIQUE NOT NULL CHECK(slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
      display_name text NOT NULL,
      role text CHECK(role IN ('owner','partner','delegated_agent','external')),
      tier integer CHECK(tier BETWEEN 1 AND 4),
      sponsor_id uuid REFERENCES principals(id),
      status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive','suspended')),
      agent_id uuid, created_by uuid REFERENCES principals(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      CHECK(kind='human' OR sponsor_id IS NOT NULL),
      CHECK(kind<>'agent' OR tier<=3),
      CHECK(role<>'external' OR tier=1),
      CHECK(role<>'partner' OR tier<=3),
      CHECK(kind='service' OR (role IS NOT NULL AND tier IS NOT NULL)),
      CHECK((kind='service' AND role IS NULL AND tier IS NULL)
         OR (kind='human' AND role IN ('owner','partner') AND tier IS NOT NULL)
         OR (kind='agent' AND role IN ('delegated_agent','external') AND tier IS NOT NULL)),
      CHECK(role<>'owner' OR tier=4)
    );
    CREATE UNIQUE INDEX one_owner ON principals(role) WHERE role='owner';
    CREATE FUNCTION immutable_principal_slug() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.slug IS DISTINCT FROM OLD.slug THEN
        RAISE EXCEPTION 'principal slug is immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER principal_slug_immutable BEFORE UPDATE ON principals
      FOR EACH ROW EXECUTE FUNCTION immutable_principal_slug();
    CREATE TABLE users (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      principal_id uuid UNIQUE NOT NULL REFERENCES principals(id),
      email text NOT NULL, password_hash text NOT NULL,
      failed_logins integer NOT NULL DEFAULT 0 CHECK(failed_logins>=0),
      locked_until timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
      last_login_at timestamptz
    );
    CREATE UNIQUE INDEX user_email_lower ON users(lower(email));
    CREATE FUNCTION require_human_user() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS(SELECT 1 FROM principals WHERE id=NEW.principal_id AND kind='human') THEN
        RAISE EXCEPTION 'login requires a human principal' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER user_human BEFORE INSERT OR UPDATE ON users
      FOR EACH ROW EXECUTE FUNCTION require_human_user();
    CREATE TABLE admin_sessions (
      id_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id),
      created_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL,
      expires_at timestamptz NOT NULL, revoked_at timestamptz, ip text, user_agent text
    );
    CREATE TABLE credential_templates (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text UNIQUE NOT NULL,
      target_role text, target_tier integer, scopes text[] NOT NULL,
      namespace_grants_template jsonb NOT NULL DEFAULT '[]',
      default_expiry_days integer NOT NULL CHECK(default_expiry_days>0),
      requires_owner_approval boolean NOT NULL DEFAULT false,
      created_by uuid REFERENCES principals(id), active boolean NOT NULL DEFAULT true
    );
    CREATE TABLE credentials (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      principal_id uuid NOT NULL REFERENCES principals(id), token_hash text UNIQUE NOT NULL,
      token_prefix text NOT NULL, name text NOT NULL,
      kind text NOT NULL CHECK(kind IN ('api','personal_ai_client','legacy_shared')),
      client_label text, ai_client boolean NOT NULL, scopes text[] NOT NULL,
      template_id uuid REFERENCES credential_templates(id), issued_by uuid REFERENCES principals(id),
      created_at timestamptz NOT NULL, expires_at timestamptz,
      last_used_at timestamptz, revoked_at timestamptz, revoked_by uuid REFERENCES principals(id),
      revoke_reason text, rate_limit integer NOT NULL DEFAULT 120 CHECK(rate_limit>0)
    );
    CREATE TABLE namespaces (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), path ltree UNIQUE NOT NULL,
      description text NOT NULL DEFAULT '', governed boolean NOT NULL DEFAULT false,
      mode text NOT NULL DEFAULT 'flag' CHECK(mode IN ('flag','queue')),
      conflict_threshold numeric, zoho_account_id text, org_entity_id uuid,
      owner_principal_id uuid REFERENCES principals(id),
      created_by uuid REFERENCES principals(id), created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE namespace_grants (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), principal_id uuid NOT NULL REFERENCES principals(id),
      namespace_id uuid NOT NULL REFERENCES namespaces(id),
      access text NOT NULL CHECK(access IN ('read','write')),
      granted_by uuid REFERENCES principals(id), granted_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(principal_id,namespace_id,access)
    );
    CREATE TABLE approvals (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(), requester_id uuid NOT NULL REFERENCES principals(id),
      required_reviewer_id uuid NOT NULL REFERENCES principals(id),
      operation text NOT NULL, payload jsonb NOT NULL,
      status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','denied','expired')),
      created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
      reviewed_at timestamptz, reviewed_by uuid REFERENCES principals(id)
    );
    CREATE TABLE notifications (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      recipient_principal_id uuid NOT NULL REFERENCES principals(id),
      kind text NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL,
      delivered_at timestamptz
    );
    CREATE TABLE bootstrap_state (
      singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
      consumed_at timestamptz NOT NULL, owner_principal_id uuid NOT NULL REFERENCES principals(id)
    );
    CREATE TABLE audit_events (
      seq bigserial PRIMARY KEY, id uuid UNIQUE NOT NULL, occurred_at timestamptz NOT NULL,
      principal_id uuid REFERENCES principals(id), sponsor_id uuid REFERENCES principals(id),
      actor text NOT NULL, credential_id uuid REFERENCES credentials(id),
      surface text NOT NULL, operation text NOT NULL, resource_type text NOT NULL,
      resource_id uuid, namespace_id uuid REFERENCES namespaces(id), namespace text,
      outcome text NOT NULL CHECK(outcome IN ('ALLOW','DENY','QUEUE')), record_status text,
      decision_trace jsonb NOT NULL, request_meta jsonb NOT NULL,
      prev_hash char(64) NOT NULL, hash char(64) NOT NULL
    );
    CREATE INDEX audit_sponsor_time ON audit_events(sponsor_id,occurred_at,seq);
    CREATE INDEX audit_principal_time ON audit_events(principal_id,occurred_at,seq);
    CREATE INDEX grants_lookup ON namespace_grants(principal_id,namespace_id,access);
    GRANT USAGE ON SCHEMA public TO cmh_app;
    REVOKE CREATE ON SCHEMA public FROM cmh_app;
    """)
    for table in TABLES:
        if table == "audit_events":
            op.execute("GRANT SELECT,INSERT ON audit_events TO cmh_app")
            op.execute("GRANT USAGE,SELECT ON SEQUENCE audit_events_seq_seq TO cmh_app")
        else:
            op.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO cmh_app")
    op.execute("RESET ROLE")


def downgrade():
    op.execute("SET LOCAL ROLE cmh_migrate")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table} CASCADE")
    op.execute("DROP FUNCTION immutable_principal_slug()")
    op.execute("DROP FUNCTION require_human_user()")
    op.execute("RESET ROLE")
