"""Count exact native-door context joins in one closed V15 healthy trace."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

IDENTITY = ("siteId", "node", "actorEpochOrdinal", "occurrenceId",
            "ordinal", "exceptionClass")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def audit(trace: Path, native: Path) -> dict:
    raw = Counter()
    statuses = Counter()
    enters = {}
    claimed_calls = []
    target = Counter()
    with trace.open() as stream:
        for line in stream:
            row = json.loads(line)
            kind = row.get("event")
            if kind == "NATIVE_FAULT_DOOR":
                key = tuple(row.get(field) for field in IDENTITY)
                raw[key] += 1
                statuses[row.get("identityStatus", "missing")] += 1
                call = row.get("callId", 0)
                if row.get("identityStatus") == "owner_matches_active_receiver":
                    assert call and row.get("receiverObjectId")
                    assert row.get("method") == row["siteId"].rsplit("#u", 1)[0]
                    claimed_calls.append((call, row["method"], row["receiverObjectId"]))
            elif kind == "METHOD_ENTER":
                enters[row.get("callId")] = (row.get("method"), row.get("objectId"))
            elif kind in ("TARGET_CHECK", "TARGET_THROW"):
                target[kind] += 1
    verified_call_joins = sum(enters.get(call) == (method, obj)
                              for call, method, obj in claimed_calls)
    assert verified_call_joins == len(claimed_calls)
    events = Counter()
    with native.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("kind") == "FAULT_DOOR":
                events[tuple(row.get(field) for field in IDENTITY)] += 1
            elif row.get("kind") in ("FAULT_APPLIED", "TARGET_CHECK", "TARGET_THROW"):
                target["native_" + row["kind"]] += 1
    matched = raw & events
    return {"raw_trace_sha256": sha(trace), "native_events_sha256": sha(native),
            "raw_door_rows": sum(raw.values()), "native_door_rows": sum(events.values()),
            "exact_six_field_matches": sum(matched.values()),
            "unmatched_raw_rows": sum((raw - events).values()),
            "unmatched_native_rows": sum((events - raw).values()),
            "duplicate_raw_identities": sum(c > 1 for c in raw.values()),
            "duplicate_native_identities": sum(c > 1 for c in events.values()),
            "identity_status": dict(statuses),
            "verified_original_call_joins": verified_call_joins,
            "target": dict(target)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthy", type=Path, required=True)
    args = parser.parse_args()
    trace = args.healthy / "trace/runtime_trace.jsonl"
    events = args.healthy / "fault-events.jsonl"
    assert trace.is_file() and events.is_file()
    result = audit(trace, events)
    path = args.healthy / "native-door-join-audit.json"
    assert not path.exists()
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
