"""Shared leading-tag parser for compatibility writes and the later import phase."""

import math
import re
from datetime import UTC, datetime

from cmh.policy.evaluator import deny

SOURCE_CONFIDENCE = {
    "direct": ("conversation", 0.85), "reported": ("human_input", 0.75),
    "consolidated": ("agent_inference", 0.70), "memory-maintenance": ("agent_inference", 0.65),
    "reconstructed": ("agent_inference", 0.60), "inferred": ("agent_inference", 0.50),
}
SOURCE_TYPES = {
    "conversation", "human_input", "agent_inference", "document", "tool_output",
    "meeting_intelligence", "source_sync", "legacy_v1",
}
REF_REQUIRED = {"document", "tool_output", "meeting_intelligence", "source_sync"}
IDENTITY_FIELDS = {"author", "author_id", "author_principal_id", "actor",
                   "principal_id", "agent_slug", "gpt_role"}


def timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise TypeError("Invalid timestamp")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def parse_tags(content):
    match = re.match(r"^(?:\s*\[[a-z_-]+:[^\]]+\])+", content or "")
    original = match.group(0).strip() if match else ""
    tags = dict(re.findall(r"\[([a-z_-]+):\s*([^\]]+)\]", original))
    return {key: value.strip() for key, value in tags.items()}, original


def provenance(context, payload, now, compatibility=False):
    meta = {"claimed": {key: payload[key] for key in IDENTITY_FIELDS if key in payload}}
    values = {key: payload.get(key) for key in ("source_type", "source_ref", "confidence",
                                              "occurred_at")}
    if compatibility:
        tags, original = parse_tags(payload.get("content", ""))
        if original:
            meta["original_tags"] = original
            meta["claimed"].update({key: value for key, value in tags.items() if key == "agent"})
        default_source = "conversation" if context.principal["kind"] == "human" else "agent_inference"
        source, confidence = SOURCE_CONFIDENCE.get(tags.get("source"), (default_source, 0.70))
        defaults = {"source_type": source, "confidence": confidence,
                    "occurred_at": tags.get("date", now)}
        for key, value in defaults.items():
            if key not in payload:
                values[key] = value
                meta["provenance_defaulted"] = True
    if any(values[key] is None for key in ("source_type", "confidence", "occurred_at")):
        return None, meta, deny("PROVENANCE_INCOMPLETE", 7)
    confidence = values["confidence"]
    if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence) or not 0 <= confidence <= 1
        or not isinstance(values["source_type"], str)
        or values["source_type"] not in SOURCE_TYPES
        or (values["source_ref"] is not None and not isinstance(values["source_ref"], str))):
        return None, meta, deny("VALIDATION_FAILED", 7)
    if values["source_type"] in REF_REQUIRED and not values["source_ref"]:
        return None, meta, deny("PROVENANCE_INCOMPLETE", 7)
    try:
        values["occurred_at"] = timestamp(values["occurred_at"])
    except (ValueError, TypeError):
        return None, meta, deny("VALIDATION_FAILED", 7)
    return values, meta, None
