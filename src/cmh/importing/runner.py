"""Owner-administrated, audited local import. No route or MCP tool exposes this class."""
import csv
import json
from collections import Counter
from uuid import uuid4

from sqlalchemy import text

from cmh.auth.context import PrincipalContext
from cmh.importing.capability import import_record, roster_spec
from cmh.importing.namespaces import row_id
from cmh.importing.plan import require_review_files
from cmh.importing.shapes import KINDS, shape
from cmh.kernel import NATIVE, operation
from cmh.services import administration, management
from cmh.services.entities import encode

EXCLUDED = {"users", "api_keys", "api_request_logs", "invitation_tokens"}


def rows(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class ImportRunner:
    def __init__(self, entities, owner):
        self.entities = entities
        self.identity = entities.identity
        self.engine = entities.engine
        self.owner = owner
        self.aliases = {}
        self.by_slug = {}

    def ensure_roster(self, roster):
        self.identity.perform(self.owner, "principals.admin", audit_operation="import.roster_review")
        imported = [row for row in roster if row["action"] == "import"]
        owners = [row for row in imported if row["role"] == "owner"]
        with self.engine.connect() as conn:
            native = conn.execute(text("""SELECT p.* FROM principals p JOIN bootstrap_state b
              ON p.id=b.owner_principal_id WHERE p.role='owner'""")).mappings().one_or_none()
        if (len(owners) != 1 or not native or owners[0]["slug"] != native["slug"]
            or native["id"] != self.owner.id or native["tier"] != 4):
            raise ValueError("Owner must match the single native bootstrap Owner")
        created = 0
        for row in sorted(imported, key=lambda x: x["kind"] != "human"):
            with self.engine.connect() as conn:
                existing = conn.execute(text("SELECT * FROM principals WHERE slug=:slug"),
                                        {"slug": row["slug"]}).mappings().one_or_none()
                sponsor = conn.execute(text("SELECT id FROM principals WHERE slug=:slug"),
                                       {"slug": row["sponsor"]}).scalar() if row["sponsor"] else None
            if existing:
                if existing["kind"] != row["kind"]:
                    raise ValueError("Existing roster principal kind conflicts with review")
                if row["kind"] == "human" and (
                    existing["role"] != row["role"] or existing["tier"] != (4 if row["role"] == "owner" else 3)
                ):
                    raise ValueError("Existing human role/tier conflicts with review")
                if row["kind"] == "agent" and (
                    existing["tier"] != int(row["tier"]) or existing["sponsor_id"] != sponsor
                    or existing["status"] != row["status"]
                ):
                    raise ValueError("Existing agent tier/sponsor/status conflicts with review")
                principal = dict(existing)
            else:
                if row["role"] == "owner":
                    raise ValueError("Owner must come from bootstrap")
                result = management.create_principal(self.identity, self.owner, {
                    "kind": row["kind"], "slug": row["slug"], "display_name": row["name"],
                    "role": row["role"] or ("delegated_agent" if row["kind"] == "agent" else None),
                    "tier": int(row["tier"]), "sponsor_id": sponsor,
                    "template": "openclaw-agent-standard",
                }, approved=True, _import_spec=roster_spec(row))
                if "principal" not in result:
                    raise ValueError("Reviewed principal failed administration policy")
                principal = result["principal"]
                created += 1
            self.by_slug[row["slug"]] = principal
            for alias in [row["slug"], row["name"], row["v1_id"], *json.loads(row["aliases"])]:
                if alias:
                    self.aliases[str(alias).casefold()] = principal["id"]
        return {"created": created, "reused": len(imported) - created}

    def namespace(self, path):
        with self.engine.connect() as conn:
            found = conn.execute(text("SELECT id FROM namespaces WHERE path=CAST(:path AS ltree)"),
                                 {"path": path}).scalar()
        if not found:
            def change(conn):
                return conn.execute(text("""INSERT INTO namespaces(path,created_by)
                  VALUES(CAST(:path AS ltree),:id) RETURNING id"""),
                                    {"path": path, "id": self.owner.id}).scalar_one()
            outcome = self.identity.perform(self.owner, "grants.admin", change=change)
            if isinstance(outcome, dict) and outcome.get("outcome") == "DENY":
                raise ValueError("Reviewed namespace failed administration policy")
            self.owner.policy_cache.clear()

    def service_context(self):
        scopes = sorted({operation(kind, write) for kind in NATIVE for write in (False, True)})
        with self.engine.connect() as conn:
            selected = conn.execute(text("""SELECT name FROM credential_templates
              WHERE name='service-integration'""")).scalar_one()
            principal = conn.execute(text("SELECT * FROM principals WHERE slug='v1-import'")).mappings().first()
        payload = {"kind": "service", "slug": "v1-import", "display_name": "v1-import",
                   "sponsor_id": self.owner.id, "template": selected, "name": "v1-import-run",
                   "credential_name": "v1-import-run", "scopes": scopes}
        if not principal:
            result = management.create_principal(self.identity, self.owner, payload, approved=True)
            if "principal" not in result:
                raise ValueError("Import service principal failed administration policy")
            principal = result["principal"]
            credential = result["credential"]
        else:
            result = management.issue_credential(self.identity, self.owner,
                                                {**payload, "principal_id": principal["id"]}, approved=True)
            credential = result.get("credential", result)
        if "id" not in credential:
            raise ValueError("Import credential failed administration policy")
        def grant(conn):
            conn.execute(text("""INSERT INTO namespace_grants(principal_id,namespace_id,access,granted_by)
              SELECT :id,id,'write',:owner FROM namespaces WHERE path='org'::ltree
              ON CONFLICT DO NOTHING"""), {"id": principal["id"], "owner": self.owner.id})
        context = PrincipalContext(dict(principal), {key: value for key, value in credential.items()
                                   if key != "token"}, request_meta={"surface": "import"})
        try:
            self.identity.perform(self.owner, "grants.admin", change=grant)
        except Exception:
            self.revoke(context)
            raise
        return context

    def revoke(self, context):
        administration.revoke(self.identity, self.owner, context.credential["id"],
                              {"reason": "v1 import run completed or failed"})

    def apply(self, source, directory):
        self.identity.perform(self.owner, "principals.admin", audit_operation="import.apply_review")
        checksums = require_review_files(directory)
        roster = rows(directory / "roster_review.csv")
        principals = self.ensure_roster(roster)
        attribution = {row["value"].casefold(): self.aliases.get(row["proposed_principal"].casefold())
                       if row["proposed_principal"] else None
                       for row in rows(directory / "attribution_review.csv")}
        mappings = rows(directory / "namespace_mapping.csv")
        paths = {(row["v1_table"], row["v1_id"]): row["proposed_namespace"] for row in mappings}
        for path in sorted(set(paths.values()), key=lambda p: (p.count("."), p)):
            # Create intermediates so the effective namespace tree stays complete.
            for index in range(1, len(path.split(".")) + 1):
                self.namespace(".".join(path.split(".")[:index]))
        run = str(uuid4())
        report = {"run_id": run, "checksums": checksums, "source_rows": sum(source["counts"].values()),
                  "imported": 0, "existing": 0, "skipped": 0, "resolved": 0, "failed": 0,
                  "principals": principals, "tables": {}, "complete": False,
                  "alias_hit_counts": dict(Counter(alias.strip() for row in mappings
                    for alias in row.get("matched_aliases", "").split(" | ") if alias.strip()))}
        def start(conn):
            conn.execute(text("""INSERT INTO import_runs(id,mode,checksums,started_at)
              VALUES(:id,'apply',CAST(:checksums AS jsonb),:now)"""),
                         {"id": run, "checksums": encode(checksums), "now": self.identity.now()})
        self.identity.perform(self.owner, "principals.admin", change=start,
                              audit_operation="import.run_start")
        context = self.service_context()
        self.context = context
        try:
            order = ["agent_directory", "agent_sessions", "gpt_messages", "unstructured_data",
                     "project_decisions", "skills", "resources", "skill_files", "memory_links"]
            order += sorted(set(source["counts"]) - set(order))
            for table in order:
                count = source["counts"].get(table, 0)
                counts = {"source": count, "imported": 0, "existing": 0, "skipped": 0, "resolved": 0}
                report["tables"][table] = counts
                if table in EXCLUDED:
                    counts["skipped"] = count
                    report["skipped"] += count
                    continue
                records = source["tables"].get(table, [])
                if len(records) != count:
                    raise ValueError("Apply source inventory is incomplete")
                for row in records:
                    locator = row_id(table, row, source.get("primary_keys", {}))
                    trace = {"v1_table": table, "v1_id": locator, "run_id": run}
                    path = paths.get((table, locator), "org" if table == "waitlist" else None)
                    if not path:
                        raise ValueError("An apply row is missing a reviewed namespace")
                    if table in KINDS:
                        status = self.entity(table, row, locator, path, trace, attribution)
                    else:
                        from cmh.importing.operational import apply_operational
                        status = apply_operational(self, table, row, locator, path, trace, roster)
                    counts[status] += 1
                    report[status] += 1
            report["complete"] = (report["imported"] + report["existing"] + report["skipped"]
                                  + report["resolved"] == report["source_rows"])
        except Exception as error:
            report["failed"] = 1
            report["errors"] = [{"v1_table": table, "error_type": type(error).__name__}]
            raise
        finally:
            self.revoke(context)
            def finish(conn):
                conn.execute(text("""UPDATE import_runs SET finished_at=:now,counts=CAST(:counts AS jsonb)
                  WHERE id=:id"""), {"now": self.identity.now(), "counts": encode(report), "id": run})
            self.identity.perform(self.owner, "principals.admin", change=finish,
                                  audit_operation="import.run_finish")
        return report

    def entity(self, table, row, locator, path, trace, attribution):
        with self.engine.begin() as conn:
            readable = self.entities.scope(conn, self.context)
            existing = conn.execute(text("""SELECT id FROM entities
              WHERE namespace_id=ANY(CAST(:readable AS uuid[]))
                AND legacy_meta->>'v1_table'=:table AND legacy_meta->>'v1_id'=:id"""),
                                    {"readable": readable, "table": table, "id": locator}).scalar()
        if existing:
            return "existing"
        item = shape(table, row, locator, self.aliases, attribution, self.identity.now())
        if table == "shared_contexts":
            from cmh.services.compat_common import old_identity

            refs, unresolved = [], []
            with self.engine.begin() as conn:
                readable = self.entities.scope(conn, self.context)
                for raw in row.get("memory_refs") or []:
                    found = self.entities.find(conn, readable, old_identity(raw, "unstructured_data"), ["memory"])
                    (refs if found else unresolved).append(str(found["id"]) if found else raw)
            item["data"]["memory_ref_entity_ids"] = refs
            if unresolved:
                item["legacy_meta"].setdefault("unresolved", {})["memory_refs"] = unresolved
        about = None
        if table == "memory_links":
            candidate = row.get("pinecone_vector_id") or row.get("memory_id") or row.get("pinecone_id")
            with self.engine.begin() as conn:
                readable = self.entities.scope(conn, self.context)
                about = conn.execute(text("""SELECT id FROM entities
                  WHERE namespace_id=ANY(CAST(:readable AS uuid[])) AND kind='memory'
                    AND (legacy_meta->>'v1_id'=:value OR legacy_meta->>'pinecone_id'=:value)"""),
                                     {"readable": readable, "value": candidate}).scalar_one_or_none()
            if not about:
                raise ValueError("Imported memory link has no readable about endpoint")
        imported = import_record(item["author"], item["created_at"], item["updated_at"], trace)
        result = self.entities.create(self.context, item["kind"], item["data"], item["provenance"],
                                      path, item["title"], item["legacy_meta"], about,
                                      _import_record=imported)
        if "id" not in result:
            raise ValueError("Import write denied: " + result.get("code", "UNKNOWN"))
        return "imported"
