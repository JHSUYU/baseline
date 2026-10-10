"""Future healthy-run analyzer: observed watcher-to-target paths only."""

from __future__ import annotations

from collections import defaultdict
import sys
from pathlib import Path

from call_return import add_balanced_returns

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"))
from Mallory.core import feedback  # noqa: E402
from Mallory.core.events import event_address, event_seq  # noqa: E402
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

DOOR = ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
        "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1")
CHECK = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor#getAliasProps"
         "(Lorg/apache/solr/request/SolrQueryRequest;Ljava/lang/String;)Ljava/util/Map;"
         "@132:branch:1")
ALIAS_KEY = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#aliases"
BASE_ANALYZE = feedback.analyze


class ReturnOccurrenceGraph(OccurrenceGraph):
    def __init__(self, events, *, reject_coarse_roots=False):
        super().__init__(events, reject_coarse_roots=reject_coarse_roots)
        add_balanced_returns(self, events, event_address, event_seq)
        self._add_actual_reference_edges(events)

    def _add_actual_reference_edges(self, events):
        """Join one actual field value write to reads of that same reference.

        The legacy numeric version remains sampled and is never upgraded.
        Repeated writes of the same reference are ambiguous and add no edge.
        """
        writers = defaultdict(list)
        for row in events:
            if (row.get("type") == "STATE_WRITE" and
                    row.get("identity_kind") == "reference_value" and
                    row.get("value_object") not in (None, "static") and
                    row.get("object") not in (None, "static") and row.get("key")):
                key = tuple(row.get(field) for field in
                            ("node", "epoch", "object", "key", "value_object"))
                writers[key].append(row)
        for read in events:
            if (read.get("type") != "STATE_READ" or
                    read.get("identity_kind") != "reference_value" or
                    read.get("value_object") in (None, "static") or
                    read.get("object") in (None, "static") or not read.get("key")):
                continue
            key = tuple(read.get(field) for field in
                        ("node", "epoch", "object", "key", "value_object"))
            matches = writers.get(key, ())
            if len(matches) != 1 or event_seq(matches[0]) >= event_seq(read):
                continue
            self._add(matches[0], read, "state_ref",
                      "unique_actual_field_reference_value")
        self._time_cache.clear()


def analyze(trace, target, plan, **kwargs):
    """Keep only exact typed watcher doors with an observed event-time path."""
    if target.get("check_sites") != [CHECK]:
        raise ValueError("SOLR-40 v2 exact target changed")
    prior = feedback.OccurrenceGraph
    try:
        feedback.OccurrenceGraph = ReturnOccurrenceGraph
        result = BASE_ANALYZE(trace, target, plan, **kwargs)
    finally:
        feedback.OccurrenceGraph = prior
    graph = ReturnOccurrenceGraph(trace.events, reject_coarse_roots=True)
    ids = {row["id"]: row for row in trace.events if isinstance(row.get("id"), str)}
    checks = [row for row in trace.events if row.get("type") == "TARGET_CHECK"
              and row.get("site") == CHECK]
    qualified: dict[str, dict] = {}
    reference_edges = []
    for edge in graph.edges:
        if edge.kind != "state_ref" or edge.certainty != "observed":
            continue
        write, read = ids.get(edge.producer_event), ids.get(edge.consumer_event)
        if (write and read and write.get("type") == "STATE_WRITE" and
                read.get("type") == "STATE_READ" and
                write.get("key") == read.get("key") == ALIAS_KEY and
                write.get("object") == read.get("object") and
                write.get("value_object") == read.get("value_object") and
                write.get("value_object") not in (None, "static") and
                write.get("identity_kind") == read.get("identity_kind") ==
                "reference_value" and
                "#setIfNewer" in str(write.get("site")) and
                "#getAliases" in str(read.get("site"))):
            reference_edges.append((edge, write, read))
    for door in trace.events:
        if (door.get("type") != "DOOR_OBSERVED" or door.get("site") != DOOR or
                door.get("fault_type") != "EXCEPTION" or
                door.get("exception_class") !=
                "org.apache.zookeeper.KeeperException$ConnectionLossException"):
            continue
        for check in checks:
            if (door.get("node") != check.get("node") or
                    door.get("epoch") != check.get("epoch")):
                continue
            for edge, write, read in reference_edges:
                if (write.get("node") != door.get("node") or
                        write.get("epoch") != door.get("epoch") or
                        read.get("node") != check.get("node") or
                        read.get("epoch") != check.get("epoch")):
                    continue
                before = graph.event_path(door, write, include_candidates=False,
                                          require_edge=False)
                after = graph.event_path(read, check, include_candidates=False,
                                         require_edge=False)
                if before is None or after is None:
                    continue
                path = (*before, edge, *after)
                if not any(part.kind == "return" for part in path):
                    continue
                qualified[door["id"]] = {
                    "target_event": check["id"],
                    "reference_write_event": write["id"],
                    "reference_read_event": read["id"],
                    "edge_kinds": [part.kind for part in path],
                }
                break
            if door["id"] in qualified:
                break
    selected = [door for door in result.get("doors", [])
                if door.get("event_id") in qualified and door.get("in_closure") is True]
    result["doors"] = selected
    result["eligible_doors_before_target"] = len(selected)
    result["watcher_observed_path_doors"] = len(selected)
    result["watcher_handoff_evidence"] = "observed_event_time_path_only"
    result["watcher_exact_reference_witnesses"] = qualified
    if not plan and result.get("status") == "observed" and not selected:
        result["status"] = "healthy_exact_watcher_handoff_missing"
    return result
