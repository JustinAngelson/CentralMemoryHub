"""Review deltas extend approvals; they cannot silently replace base decisions."""
import csv
import hashlib
import json

from cmh.importing.plan import REVIEW_FILES, write_plan

KEYS = {"roster_review.csv": lambda r: r["v1_id"] or "slug:" + r["slug"],
        "attribution_review.csv": lambda r: r["value"].casefold(),
        "namespace_mapping.csv": lambda r: (r["v1_table"], r["v1_id"])}
PARTS = dict(zip(REVIEW_FILES, ("roster", "attribution", "namespaces"), strict=True))


def read_rows(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def delta_plan(plan, directory):
    output = dict(plan)
    for name, part in PARTS.items():
        reviewed = {KEYS[name](r) for r in read_rows(directory / name)}
        output[part] = [r for r in plan[part] if KEYS[name](r) not in reviewed]
    return output


def write_delta(plan, directory):
    # Reuse the original formats without overwriting approved files.
    import tempfile

    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        from pathlib import Path

        staging = Path(temporary)
        write_plan(plan, staging)
        for name in REVIEW_FILES:
            (staging / name).replace(directory / name.replace(".csv", "_delta.csv"))
        (staging / "reconciliation_preview.md").replace(directory / "delta_preview.md")


def approved_reviews(directory):
    expected = json.loads((directory / "review-file-checksums.json").read_text())
    names = list(REVIEW_FILES)
    deltas = [n.replace(".csv", "_delta.csv") for n in REVIEW_FILES]
    if any((directory / n).exists() for n in deltas):
        names += deltas
    actual = {}
    result = {}
    for name in names:
        actual[name] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if expected.get(name) != actual[name]:
            raise ValueError("Approved base/delta checksum changed or missing")
    for name in REVIEW_FILES:
        result[name] = read_rows(directory / name)
        delta = name.replace(".csv", "_delta.csv")
        seen = {KEYS[name](r) for r in result[name]}
        for row in read_rows(directory / delta) if delta in names else []:
            key = KEYS[name](row)
            if key in seen:
                raise ValueError("Delta collides with an approved review row")
            seen.add(key)
            result[name].append(row)
    return result, actual
