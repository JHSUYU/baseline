#!/usr/bin/env python3
"""Recheck the sealed v4 source-backed path without starting a Solr JVM."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402
from audit_exact_path import ASSIGNED, CONSUMED, GUARD_READ, PUBLISHED, REGION  # noqa: E402

PREFIX = "solr37_strict_fault_pilot_v4_node0/SOLR-37/pilot/trials/r0000/"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def main() -> int:
    config = json.loads((HERE / "config-pilot-node0.json").read_text())
    pinned = config["v4_actor_drift_observation"]
    archive = Path(pinned["archive"])
    receipt = json.loads(Path(pinned["receipt"]).read_text())
    require(hashlib.sha256(archive.read_bytes()).hexdigest() == pinned["archive_sha256"],
            "sealed v4 archive hash changed")
    require(receipt["archive_sha256"] == pinned["archive_sha256"],
            "sealed v4 receipt differs")
    with tarfile.open(archive, "r:gz") as source:
        trace_gz = source.extractfile(PREFIX + "events.jsonl.gz").read()
        log = source.extractfile(PREFIX + "junit.log").read().decode("utf-8")
    require(hashlib.sha256(trace_gz).hexdigest() == receipt["trace_sha256"],
            "sealed v4 trace hash changed")
    trace_raw = gzip.decompress(trace_gz)
    events = tuple(json.loads(line) for line in io.BytesIO(trace_raw) if line.strip())
    by_id = {event.get("id"): event for event in events}
    door = by_id[pinned["broad_source_witness_door"]]
    target = by_id[pinned["exact_target"]]
    require((door.get("node"), door.get("epoch")) == ("shard-2", 0)
            and (target.get("node"), target.get("epoch")) == ("shard-2", 0)
            and door.get("region") == REGION and "@1641:" in door.get("site", "")
            and "@994:" in target.get("site", "")
            and door["seq"] < target["seq"], "door or target actor/site changed")
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    path = graph.event_path(door, target, include_candidates=False, require_edge=True)
    require(bool(path), "no observed event-time path")
    links = [(by_id[edge.producer_event], by_id[edge.consumer_event])
             for edge in path if edge.kind == "state" and edge.certainty == "observed"]
    reference_links = [(a, b) for a, b in links
                       if (a.get("site"), b.get("site")) in
                       ((PUBLISHED, CONSUMED), (ASSIGNED, GUARD_READ))]
    require(len(reference_links) == 2, "missing observed exact-reference state edges")
    for writer, reader in reference_links:
        require(writer.get("object") == reader.get("object")
                and writer.get("version") == reader.get("version")
                and writer.get("version_confidence") == "exact"
                and reader.get("version_confidence") == "exact"
                and writer["seq"] < reader["seq"], "state reference identity mismatch")
    before = next(line for line in log.splitlines()
                  if "MALLORY_SOLR31_STATE phase=before" in line and
                  "task:978:1 collection=collection1" in line and "node=shard-2" in line)
    after = next(line for line in log.splitlines()
                 if "MALLORY_SOLR31_STATE phase=after" in line and
                 "task:978:1 collection=collection1" in line and "node=shard-2" in line)
    target_diag = next(line for line in log.splitlines()
                       if "MALLORY_SOLR37_STATE phase=target" in line and
                       "node=shard-2" in line and ":999:1" in line)
    reader_ids = [re.search(r"\breader_id=([0-9a-f]+)", line).group(1)
                  for line in (before, after, target_diag)]
    require(len(set(reader_ids)) == 1 and
            all("collection=collection1" in line for line in (before, after, target_diag))
            and all("path=/collections/collection1/state.json" in line
                    for line in (before, after)), "collection resource or diagnostic reader mismatch")
    reader_object = reference_links[0][0]["object"]
    earlier = [event for event in events if event.get("type") == "STATE_WRITE"
               and event.get("site") == PUBLISHED and event.get("node") == "shard-2"
               and event.get("object") == reader_object and event.get("seq", 0) < door["seq"]]
    require(earlier, "no prior exact publication at candidate door")
    previous = max(earlier, key=lambda event: event["seq"])
    print(json.dumps({"valid": True, "door_event": door["id"],
                      "target_event": target["id"], "actor": "shard-2",
                      "resource": "/collections/collection1/state.json",
                      "reader_object": reader_object,
                      "prior_exact_version_at_door": previous["version"],
                      "published_version_on_path": reference_links[0][0]["version"],
                      "observed_state_edges": [[a["id"], b["id"]]
                                               for a, b in reference_links]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
