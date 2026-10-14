"""Match client aliases without emitting any surrounding source content."""
import csv
import re

from cmh.importing.roster import safe

CONTENT_FIELDS = {
    "content", "title", "name", "description", "context", "decision", "decision_text",
    "summary", "notes", "purpose", "topic", "question", "findings", "hypothesis",
    "experiment_name", "insight", "details", "context_tag", "org_name",
    "task_name", "task_description", "feedback", "result",
}


def load_orgs(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"zoho_account_id", "name", "proposed_namespace", "aliases", "notes"}
    if not rows or not required <= set(rows[0]):
        raise ValueError("Invalid organization review input")
    owners = {}
    result = []
    for row in rows:
        ns = row["proposed_namespace"].strip()
        if ns != "org" and not re.fullmatch(r"org\.clients\.[a-z][a-z0-9_-]*", ns):
            raise ValueError("Invalid client namespace")
        aliases = [row["name"].strip(), row["zoho_account_id"].strip()]
        aliases += re.split(r"[;|\n]", row.get("aliases") or "")
        aliases += re.findall(r"\b\d{15,}\b", row.get("notes") or "")
        aliases = list(dict.fromkeys(a.strip() for a in aliases if a.strip()))
        for alias in aliases:
            key = alias.casefold()
            if key in owners and owners[key] != ns:
                raise ValueError("Client alias maps to conflicting namespaces")
            owners[key] = ns
        result.append({"namespace": ns, "aliases": aliases,
                       "zoho_account_id": row["zoho_account_id"].strip()})
    return result


def row_id(table, row, primary_keys):
    fields = primary_keys.get(table, [])
    if not fields:
        fields = [key for key in (
            "id", "agent_id", "message_id", "session_id", "skill_id", "task_id",
            "experiment_id", "decision_id", "insight_id",
        ) if key in row][:1]
    if not fields or any(row.get(key) is None for key in fields):
        raise ValueError("Source row has no non-content primary-key locator")
    return ":".join(str(row[key]) for key in fields)


def make_namespaces(tables, orgs, primary_keys):
    result = []
    for table, rows in sorted(tables.items()):
        for row in rows:
            text = "\n".join(str(v) for k, v in row.items()
                             if k in CONTENT_FIELDS and isinstance(v, str))
            matches = [(org["namespace"], alias) for org in orgs for alias in org["aliases"]
                       if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text,
                                    0 if len(alias) <= 3 else re.IGNORECASE)]
            namespaces = {ns for ns, _ in matches if ns != "org"}
            if len(namespaces) == 1:
                ns, reason = next(iter(namespaces)), "single-client-namespace"
            elif len(namespaces) > 1:
                ns, reason = "org", "multiple-client-namespaces"
            else:
                ns, reason = "org", "own-org" if matches else "no-client-match"
            result.append({"v1_table": table, "v1_id": row_id(table, row, primary_keys),
                           "proposed_namespace": ns,
                           "matched_aliases": " | ".join(sorted({safe(a) for _, a in matches})),
                           "reason": reason, "review_required": "yes"})
    return result


def alias_hit_counts(tables, orgs):
    """Actual whole-word occurrences, including zeroes, without emitting source text."""
    counts = {alias: 0 for org in orgs for alias in org["aliases"]}
    patterns = {alias: re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)",
                                 0 if len(alias) <= 3 else re.IGNORECASE)
                for alias in counts}
    for table, rows in tables.items():
        if table == "waitlist":
            continue
        for row in rows:
            content = "\n".join(str(value) for key, value in row.items()
                                if key in CONTENT_FIELDS and isinstance(value, str))
            for alias, pattern in patterns.items():
                counts[alias] += len(pattern.findall(content))
    return counts
