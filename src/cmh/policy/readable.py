"""Bulk read visibility. Mirrors evaluator.can_access and sponsor_ceiling (read).

The database supplies one consistent namespace/grant/principal snapshot. The
policy comparison is in memory, never one SQL round trip per namespace.
"""

from collections import defaultdict

from sqlalchemy import text


def readable_namespaces(connection, subject):
    nodes = list(connection.execute(text(
        "SELECT id,path::text AS path,mode,owner_principal_id FROM namespaces"
    )).mappings())
    by_path = {node["path"]: node for node in nodes}
    people = {node["owner_principal_id"] for node in nodes if node["owner_principal_id"]}
    people.update((subject["id"], subject.get("sponsor_id")))
    principals = {row["id"]: dict(row) for row in connection.execute(text(
        "SELECT * FROM principals WHERE id=ANY(CAST(:ids AS uuid[]))"
    ), {"ids": list(people - {None})}).mappings()}
    principal_ids = list({subject["id"], subject.get("sponsor_id")} - {None})
    grants = defaultdict(list)
    for row in connection.execute(text("""
        SELECT g.principal_id,n.path::text AS path,g.access
        FROM namespace_grants g JOIN namespaces n ON n.id=g.namespace_id
        WHERE g.principal_id=ANY(CAST(:ids AS uuid[]))
    """), {"ids": principal_ids}).mappings():
        grants[row["principal_id"]].append(row)
    barriers = [node["path"] for node in nodes if node["mode"] == "queue"]

    def descendant(path, parent):
        return path == parent or path.startswith(parent + ".")

    def access(actor, path):
        parts = path.split(".")
        private = len(parts) >= 3 and parts[2] == "private"
        anchor = by_path.get(".".join(parts[:3])) if private else by_path[path]
        if parts[0] == "people" and private:
            if anchor and anchor["owner_principal_id"] == actor["id"]:
                return True
            if actor["role"] == "owner":
                return False
        elif actor["role"] == "owner":
            return True
        if parts[0] == "agents" and private and anchor:
            owner = principals.get(anchor["owner_principal_id"])
            if owner and (owner["id"] == actor["id"] or owner["sponsor_id"] == actor["id"]):
                return True
        if actor["role"] == "external" and path == "inbox":
            return True
        return any(descendant(path, grant["path"]) and not any(
            descendant(path, barrier) and not descendant(grant["path"], barrier)
            for barrier in barriers
        ) for grant in grants[actor["id"]])

    sponsor = principals.get(subject.get("sponsor_id")) if subject["kind"] != "human" else None
    if subject["kind"] != "human" and (
        not sponsor or sponsor["status"] != "active" or (
            subject["kind"] == "agent" and subject["tier"] > sponsor["tier"]
        )
    ):
        return []
    return [str(node["id"]) for node in nodes if access(subject, node["path"]) and (
        subject["kind"] == "human"
        or node["path"] == "agents." + subject["slug"] + ".private"
        or access(sponsor, node["path"])
    )]
