"""Metadata-only C3 reporting queries. All callers supply a read-only connection."""
from datetime import UTC, datetime, timedelta

from c3_common import OperatorError


def parse_since(value):
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except ValueError:
        raise OperatorError("--since requires an ISO-8601 timestamp with a timezone.") from None


def audit_events(conn, principal_id, since):
    return conn.execute("""
        SELECT occurred_at AS time,operation,outcome,credential_id
        FROM audit_events WHERE principal_id=%s
          AND (%s::timestamptz IS NULL OR occurred_at >= %s)
        ORDER BY occurred_at DESC,seq DESC LIMIT 10
    """, (principal_id, since, since)).fetchall()


def legacy_usage(conn, subjects, now):
    since = now - timedelta(hours=24)
    hours, last_seen = [], []
    for subject in subjects:
        rows = conn.execute("""
            SELECT date_trunc('hour',occurred_at AT TIME ZONE 'UTC') AS hour,
              count(*) AS count
            FROM audit_events WHERE principal_id=%s
              AND occurred_at >= %s AND occurred_at < %s
              AND operation <> 'mcp.transport'
            GROUP BY 1 ORDER BY 1
        """, (subject["id"], since, now)).fetchall()
        counts = {row["hour"].replace(tzinfo=UTC): row["count"] for row in rows}
        hour = since.replace(minute=0, second=0, microsecond=0)
        while hour <= now:
            hours.append({"principal": subject["slug"], "hour_utc": hour,
                          "count": counts.get(hour, 0)})
            hour += timedelta(hours=1)
        seen = conn.execute("""
            SELECT max(occurred_at) AS last_seen FROM audit_events
            WHERE principal_id=%s AND operation <> 'mcp.transport'
        """, (subject["id"],)).fetchone()
        last_seen.append({"principal": subject["slug"], "last_seen": seen["last_seen"]})
    return {"window_start": since, "window_end": now, "hours": hours, "last_seen": last_seen}
