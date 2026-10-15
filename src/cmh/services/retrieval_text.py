"""Read-time projections from immutable typed fields; never persist derived text."""

from cmh.kernel import TYPED


def text_fields(kind):
    """Title first, then registry declaration order; never stringify metadata."""
    return tuple(dict.fromkeys([
        "title",
        *(field for field, datatype in TYPED[kind][1].items()
          if datatype in {"text", "text[]"}),
    ]))


def display_text(snapshot):
    kind = snapshot["kind"]
    # Legacy memory/note bodies must remain byte-for-byte unchanged.
    if kind in {"memory", "note"}:
        return snapshot.get("content" if kind == "memory" else "body") or ""
    parts = []
    for field in text_fields(kind):
        value = snapshot.get(field)
        if TYPED[kind][1].get(field) == "text[]" and isinstance(value, list):
            parts.extend(item for item in value if isinstance(item, str) and item)
        elif isinstance(value, str) and value:
            parts.append(value)
    return "\n".join(parts)


def historical_text_sql():
    """SQL equivalent of the typed text projection, including searchable titles.

    Identifiers and literals come exclusively from the source-controlled registry.
    No caller-supplied values are interpolated into SQL. Text arrays are flattened
    in stored order, not rendered as JSON. Non-text typed fields are excluded.
    """
    cases = []
    for kind, (_, columns) in TYPED.items():
        parts = []
        for field in text_fields(kind):
            value = f"v.snapshot->'{field}'"
            if columns.get(field) == "text[]":
                parts.append(
                    "(SELECT string_agg(item, E'\\n' ORDER BY position) "
                    "FROM jsonb_array_elements_text("
                    f"CASE WHEN jsonb_typeof({value})='array' THEN {value} "
                    "ELSE '[]'::jsonb END) WITH ORDINALITY AS items(item,position))"
                )
            else:
                parts.append(f"v.snapshot->>'{field}'")
        cases.append(f"WHEN '{kind}' THEN concat_ws(E'\\n', {', '.join(parts)})")
    return "(CASE v.snapshot->>'kind' " + " ".join(cases) + " ELSE '' END)"
