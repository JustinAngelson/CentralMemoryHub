"""Immutable bundle expansion; no wildcard scope smuggling at issuance."""

READ_RESOURCES = (
    "memory", "decisions", "knowledge", "orgstate", "entities", "directory",
    "messages", "tasks", "experiments", "insights",
)
OBSERVER = {name + ".read" for name in READ_RESOURCES}
CONTRIBUTOR = OBSERVER | {
    name + ".write" for name in (
        "memory", "decisions", "knowledge", "orgstate", "messages", "tasks",
        "experiments", "insights",
    )
} | {"memory.endorse", "decisions.endorse", "knowledge.endorse", "entities.propose_change"}
OPERATOR = CONTRIBUTOR | {"approvals.review", "digest.read"}
STEWARD = OPERATOR | {
    "audit.read", "policy.*", "grants.admin",
    "principals.admin", "credentials.admin",
}
BUNDLES = {
    "bundle:observer": OBSERVER, "bundle:contributor": CONTRIBUTOR,
    "bundle:operator": OPERATOR, "bundle:steward": STEWARD,
    "bundle:external": OBSERVER | {"inbox.write"},
    "bundle:sync": {"entities.write", "sync.*"},
}


def has_scope(scopes, operation):
    return operation in scopes or any(
        scope.endswith(".*") and operation.startswith(scope[:-1]) for scope in scopes
    )


def ceiling(scope):
    return scope.startswith("policy.") or scope in {
        "grants.admin", "principals.admin", "credentials.admin", "credentials.issue_sponsored",
    }


def envelope(principal):
    if principal["kind"] == "service":
        return set()
    scopes = {1: OBSERVER, 2: CONTRIBUTOR, 3: OPERATOR, 4: STEWARD}[principal["tier"]]
    if principal["role"] == "external":
        scopes = BUNDLES["bundle:external"]
    if principal["role"] in ("partner", "owner"):
        scopes = scopes | {"credentials.issue_sponsored"}
    return set(scopes)


def expand(scopes):
    result = set()
    for scope in scopes:
        if scope.startswith("bundle:"):
            if scope not in BUNDLES:
                raise ValueError("Unknown scope bundle")
            result.update(BUNDLES[scope])
        else:
            result.add(scope)
    return sorted(result)
