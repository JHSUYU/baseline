"""Future healthy-run analyzer: observed watcher-to-target paths only."""

from __future__ import annotations

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
            path = graph.event_path(door, check, include_candidates=False,
                                    require_edge=True)
            if path is None or not any(edge.kind == "return" for edge in path):
                continue
            exact_state = False
            for edge in path:
                if edge.kind != "state" or edge.certainty != "observed":
                    continue
                write, read = ids.get(edge.producer_event), ids.get(edge.consumer_event)
                if (write and read and write.get("type") == "STATE_WRITE" and
                        read.get("type") == "STATE_READ" and
                        write.get("key") == read.get("key") == ALIAS_KEY and
                        write.get("object") == read.get("object") and
                        write.get("value_object") == read.get("value_object") and
                        write.get("value_object") not in (None, "static") and
                        write.get("version_confidence") == "exact" and
                        read.get("version_confidence") == "exact" and
                        write.get("identity_kind") == read.get("identity_kind") ==
                        "reference_value" and
                        "#setIfNewer" in str(write.get("site")) and
                        "#getAliases" in str(read.get("site"))):
                    exact_state = True
                    break
            if exact_state:
                qualified[door["id"]] = {"target_event": check["id"],
                                          "edge_kinds": [edge.kind for edge in path]}
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
