"""Roster authority comes only from the private review defaults, not v1 metadata."""
import fnmatch
import json
import re
from collections import Counter

FIELDS = {
    "gpt_role", "made_by_agent", "created_by_agent", "assigned_to_agent",
    "executing_agent", "owner_agent", "last_updated_by", "sender_agent",
    "receiver_agent", "created_by",
}


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def safe(value):
    value = str(value).strip()
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted email]", value)
    value = re.sub(r"\b(?:sk-|Bearer )[A-Za-z0-9_.-]+", "[redacted token]", value)
    return re.sub(r"\b[0-9a-fA-F]{64}\b", "[redacted hash-like value]", value)


def make_roster(directory, config):
    names = {}
    for rule in config["rules"]:
        for name in rule["names"]:
            key = name.casefold()
            if key in names and names[key]["slug"] != rule["slug"]:
                raise ValueError("Conflicting roster defaults")
            names[key] = rule
    duplicates = {k.casefold(): v for k, v in config.get("duplicate_names", {}).items()}
    result, deferred = [], []
    for entry in directory:
        name = (entry.get("name") or "").strip()
        identity = str(entry["agent_id"])
        base = {"v1_id": identity, "name": safe(name), "review_required": "yes"}
        if not name and str(entry.get("status", "")).casefold() == "inactive":
            result.append({**base, "action": "skip", "reason": "blank-inactive",
                "slug": "", "kind": "", "role": "", "tier": "", "sponsor": "",
                "status": "inactive", "aliases": "[]"})
            continue
        if name.casefold() in duplicates:
            target = duplicates[name.casefold()]
            result.append({**base, "action": "skip", "reason": "inactive-duplicate",
                "slug": target, "kind": "", "role": "", "tier": "", "sponsor": "",
                "status": "inactive", "aliases": json.dumps([safe(name), identity])})
            deferred.append((target, name, identity))
            continue
        if not name:
            raise ValueError("An unnamed non-inactive directory row needs a roster decision")
        rule = names.get(name.casefold())
        if rule is None:
            matches = [r for r in config["rules"] if any(
                fnmatch.fnmatchcase(name.casefold(), p.casefold())
                for p in r.get("name_patterns", [])
            )]
            if len(matches) > 1:
                raise ValueError("Ambiguous roster name patterns")
            rule = matches[0] if matches else {
                "slug": slugify(name), "kind": "agent", "role": "", "tier": 1,
                "sponsor": config["owner_slug"], "status": "inactive",
            }
        result.append({**base, **{k: rule[k] for k in (
            "slug", "kind", "role", "tier", "sponsor", "status")},
            "action": "import", "reason": "configured" if name.casefold() in names else "persona-default",
            "aliases": json.dumps(list(dict.fromkeys(
                [safe(name), identity] + [safe(x) for x in rule.get("names", [])]
            )), ensure_ascii=False)})
    for entry in config.get("additions", []):
        result.append({**{k: entry[k] for k in (
            "name", "slug", "kind", "role", "tier", "sponsor", "status")},
            "v1_id": "", "action": "import", "reason": "approved-addition",
            "review_required": "yes",
            "aliases": json.dumps(list(dict.fromkeys([entry["name"], entry["slug"]])))})
    imported = [r for r in result if r["action"] == "import"]
    for row in imported:
        if row["kind"] == "human":
            row["tier"] = 4 if row["role"] == "owner" else 3
    if len({r["slug"] for r in imported}) != len(imported):
        raise ValueError("Duplicate roster slug")
    by_slug = {r["slug"]: r for r in imported}
    for target, name, identity in deferred:
        if target not in by_slug:
            raise ValueError("Duplicate roster row has no canonical principal")
        current = by_slug[target]
        current["aliases"] = json.dumps(list(dict.fromkeys(
            json.loads(current["aliases"]) + [safe(name), identity]
        )), ensure_ascii=False)
    for row in imported:
        if row["kind"] == "agent" and (
            row["tier"] not in (1, 2) or row["sponsor"] not in by_slug
            or by_slug[row["sponsor"]]["kind"] != "human"
        ):
            raise ValueError("Invalid proposed agent tier/sponsor")
    return result


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)


def make_attribution(tables, roster, config):
    counts = Counter()
    for table, entries in tables.items():
        for entry in entries:
            for field, value in entry.items():
                if field in FIELDS or (
                    table == "shared_contexts" and field in {"sender", "recipients"}
                ) or (table == "agent_sessions" and field == "agent_id"):
                    for actor in strings(value):
                        if actor.strip():
                            counts[actor.strip()] += 1
                if isinstance(value, str):
                    for actor in re.findall(r"\[agent:\s*([^\]]+)\]", value, re.IGNORECASE):
                        counts[actor.strip()] += 1
    mapping = {}

    def assign(alias, slug):
        key = alias.casefold()
        if key in mapping and mapping[key] != slug:
            raise ValueError("Conflicting attribution defaults")
        mapping[key] = slug
        counts.setdefault(alias, 0)

    slugs = {r["slug"] for r in roster if r["action"] == "import"}
    for row in roster:
        if row["slug"]:
            for alias in json.loads(row["aliases"]):
                assign(alias, row["slug"])
            assign(row["slug"], row["slug"])
    for alias, slug in config.get("attribution_aliases", {}).items():
        if slug not in slugs:
            raise ValueError("Attribution default names a missing principal")
        assign(alias, slug)
    for value in config.get("unmapped", []):
        counts.setdefault(value, 0)
    result = []
    unmapped = {s.casefold() for s in config.get("unmapped", [])}
    for value, count in sorted(counts.items(), key=lambda item: item[0].casefold()):
        slug = mapping.get(value.casefold(), "")
        reason = "roster-or-explicit-default" if slug else "unmapped"
        if not slug:
            matches = set()
            for prefix, proposed in config.get("attribution_prefixes", {}).items():
                if re.fullmatch(r"[0-9a-fA-F-]{36}", value) and value.casefold().startswith(prefix.casefold()):
                    matches.add(proposed)
            for pattern in config.get("attribution_patterns", []):
                if fnmatch.fnmatchcase(value.casefold(), pattern["pattern"].casefold()):
                    matches.add(pattern["slug"])
            if len(matches) > 1:
                raise ValueError("Ambiguous proposed attribution")
            if matches:
                slug = matches.pop()
                if slug not in slugs:
                    raise ValueError("Attribution pattern names a missing principal")
                reason = "configured-pattern"
        if value.casefold() in unmapped:
            slug, reason = "", "explicitly-unmapped"
        result.append({"value": safe(value), "count": count, "proposed_principal": slug,
                       "review_required": "yes", "reason": reason})
    return result
