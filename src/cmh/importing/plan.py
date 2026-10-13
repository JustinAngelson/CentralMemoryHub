"""Pure plan generation: never call services, embed, mint credentials or write SQL."""
import csv
import hashlib
import os
from pathlib import Path

from cmh.importing import namespaces
from cmh.importing.roster import make_attribution, make_roster

EXCLUDED = {"users", "api_keys", "api_request_logs", "invitation_tokens"}
REVIEW_FILES = ("roster_review.csv", "attribution_review.csv", "namespace_mapping.csv")


def load_orgs(path):
    return namespaces.load_orgs(path)


def build_plan(source, defaults, orgs):
    tables = {t: rows for t, rows in source["tables"].items()
              if t not in EXCLUDED | {"waitlist"}}
    roster = make_roster(tables.get("agent_directory", []), defaults)
    return {
        "roster": roster, "attribution": make_attribution(tables, roster, defaults),
        "namespaces": namespaces.make_namespaces(tables, orgs, source.get("primary_keys", {})),
        "counts": source["counts"],
        "dispositions": {t: "excluded" if t in EXCLUDED else "waitlist" if t == "waitlist"
                         else "content" for t in source["counts"]},
        "source_total": sum(source["counts"].values()),
    }


def require_review_files(directory):
    root = Path(directory)
    if any(not (root / name).is_file() for name in REVIEW_FILES):
        raise ValueError("All three approved review files are required")
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in REVIEW_FILES}


def write_csv(path, rows, fields):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            safe_row = {}
            for key in fields:
                value = row.get(key, "")
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                    value = "'" + value
                safe_row[key] = value
            writer.writerow(safe_row)


def write_plan(plan, directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    specifications = [
        ("roster_review.csv", "roster", ["v1_id", "name", "action", "kind", "role", "tier",
         "sponsor", "status", "slug", "aliases", "reason", "review_required"]),
        ("attribution_review.csv", "attribution",
         ["value", "count", "proposed_principal", "review_required", "reason"]),
        ("namespace_mapping.csv", "namespaces",
         ["v1_table", "v1_id", "proposed_namespace", "matched_aliases", "reason", "review_required"]),
    ]
    for name, key, fields in specifications:
        write_csv(root / name, plan[key], fields)
    lines = ["# Reconciliation preview — PLAN ONLY", "",
             "No target writes, principal creation, credentials, audit appends or embeddings.",
             "All proposals require owner review. This is not an apply report.", "",
             "| Source table | Rows | Disposition |", "|---|---:|---|"]
    lines += [f"| {t} | {count} | {plan['dispositions'][t]} |"
              for t, count in sorted(plan["counts"].items())]
    lines += [f"| **Total** | **{plan['source_total']}** | |", "",
              f"Roster review rows: {len(plan['roster'])}.",
              f"Proposed principals: {sum(r['action'] == 'import' for r in plan['roster'])}.",
              f"Skipped directory rows: {sum(r['action'] == 'skip' for r in plan['roster'])}.",
              f"Unmapped attribution strings: {sum(not r['proposed_principal'] for r in plan['attribution'])}.",
              f"Unmapped attribution occurrences: {sum(r['count'] for r in plan['attribution'] if not r['proposed_principal'])}.",
              "", "## Namespace review counts", ""]
    counts = {}
    for row in plan["namespaces"]:
        key = (row["proposed_namespace"], row["reason"])
        counts[key] = counts.get(key, 0) + 1
    lines += [f"- {ns}: {count} ({reason})" for (ns, reason), count in sorted(counts.items())]
    lines += ["", "The namespace CSV contains only table/ID locators, matched aliases and proposals.",
              "No source content, upload paths, email addresses or secret values are emitted."]
    path = root / "reconciliation_preview.md"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
