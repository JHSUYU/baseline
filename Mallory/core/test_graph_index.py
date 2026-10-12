"""Indexed handoff pairing must preserve the evidence of the slow oracle."""

from __future__ import annotations

from collections import defaultdict
import random
import unittest

from .events import event_address
from .graph import Edge, OccurrenceGraph


def _event(kind: str, index: int, **fields):
    return {"type": kind, "id": f"e{index}", "seq": index,
            "node": f"n{index % 3}", "epoch": 0,
            "occurrence": f"occ-{index}", **fields}


def _slow_pair(events, producer_type, consumer_type, kind, fields,
               optional=(), exclusive_consumers=False):
    """The original scan, retained here only as a small-trace test oracle."""
    producers = defaultdict(list)
    consumers = []
    gaps = defaultdict(int)
    edges = set()
    candidate_edges = set()
    for row in events:
        if row["type"] == producer_type:
            key = OccurrenceGraph._key(row, fields)
            if key is None:
                gaps[f"{kind}_producer_missing_identity"] += 1
            else:
                producers[key].append(row)
        elif row["type"] == consumer_type:
            consumers.append(row)
    for row in consumers:
        key = OccurrenceGraph._key(row, fields)
        if key is None:
            gaps[f"{kind}_consumer_missing_identity"] += 1
            continue
        matches = [producer for producer in producers.get(key, [])
                   if all(producer.get(field) == row.get(field) for field in optional)]
        if exclusive_consumers:
            peers = [other for other in consumers
                     if OccurrenceGraph._key(other, fields) == key and
                     all(other.get(field) == row.get(field) for field in optional)]
            if len(peers) != 1:
                gaps[f"{kind}_ambiguous_consumer"] += 1
                continue
        if len(matches) != 1:
            gaps[f"{kind}_{'unmatched' if not matches else 'ambiguous'}"] += 1
            continue
        producer = matches[0]
        source, target = event_address(producer), event_address(row)
        if source == target:
            continue
        observed_optional = tuple(field for field in optional if row.get(field) is not None)
        certainty = ("candidate" if kind == "state" and
                     (row.get("version_confidence") != "exact" or
                      producer.get("version_confidence") != "exact") else "observed")
        edge = Edge(source, target, kind,
                    ("sampled_version:" if certainty == "candidate" else "unique:") +
                    ",".join(fields + observed_optional),
                    producer["id"], row["id"], certainty)
        (candidate_edges if certainty == "candidate" else edges).add(edge)
    return edges, candidate_edges, gaps


class GraphIndexTest(unittest.TestCase):
    def test_indexed_pairing_matches_original_scan_on_repeated_and_ambiguous_ids(self):
        rng = random.Random(17)
        rows = []
        for index in range(600):
            kind = rng.choice(("SEND", "RECV", "TASK_SUBMIT", "TASK_CLAIM",
                               "STATE_WRITE", "STATE_READ"))
            if kind in ("SEND", "RECV"):
                fields = {"transport": "rpc", "correlation": f"rpc-{rng.randrange(12)}",
                          "port": rng.choice(("request", "response")),
                          "attempt": rng.randrange(3),
                          "half": rng.choice(("request", "response"))}
                if index % 37 == 0:
                    fields["correlation"] = ""
                if index % 53 == 0:
                    fields["attempt"] = [1]  # Exercise exact-equality fallback.
            elif kind in ("TASK_SUBMIT", "TASK_CLAIM"):
                fields = {"correlation": f"task-{rng.randrange(12)}",
                          "attempt": rng.randrange(3)}
                if index % 41 == 0:
                    fields["correlation"] = None
            else:
                fields = {"object": f"o{rng.randrange(6)}",
                          "key": f"k{rng.randrange(3)}", "version": rng.randrange(4),
                          "version_confidence": rng.choice(("exact", "sampled"))}
            rows.append(_event(kind, index, **fields))
        rows = tuple(rows)
        graph = OccurrenceGraph(rows)
        expected_edges = set()
        expected_candidates = set()
        expected_gaps = defaultdict(int)
        for args in (("SEND", "RECV", "rpc", ("transport", "correlation", "port"),
                      ("attempt", "half"), True),
                     ("TASK_SUBMIT", "TASK_CLAIM", "task", ("correlation",),
                     ("attempt",), True),
                     ("STATE_WRITE", "STATE_READ", "state",
                      ("node", "epoch", "object", "key", "version"), (), False)):
            edges, candidates, gaps = _slow_pair(rows, *args)
            expected_edges.update(edges)
            expected_candidates.update(candidates)
            for name, count in gaps.items():
                expected_gaps[name] += count
        self.assertEqual(expected_edges, graph.edges)
        self.assertEqual(expected_candidates, graph.candidate_edges)
        self.assertEqual(dict(expected_gaps), dict(graph.gaps))

    def test_jvm_local_object_ids_do_not_join_different_nodes_or_epochs(self):
        def state(kind, index, node, epoch, occurrence):
            return _event(kind, index, node=node, epoch=epoch,
                          occurrence=occurrence, object="o1", key="aliases",
                          version=1, version_confidence="sampled")
        rows = (state("STATE_WRITE", 1, "n0", 0, "writer"),
                state("STATE_READ", 2, "n1", 0, "other-node"),
                state("STATE_READ", 3, "n0", 1, "restarted"),
                state("STATE_READ", 4, "n0", 0, "same-jvm"))
        graph = OccurrenceGraph(rows)
        self.assertEqual({("e1", "e4")},
                         {(edge.producer_event, edge.consumer_event)
                          for edge in graph.candidate_edges})
        self.assertEqual(2, graph.gaps["state_unmatched"])
        self.assertFalse(graph.edges)

    def test_pairing_performs_linear_number_of_identity_lookups(self):
        rows = tuple(_event("RECV" if index & 1 else "SEND", index,
                            transport="rpc", correlation=f"rpc-{index // 2}",
                            port="request", attempt=0, half="request")
                     for index in range(1000))

        class CountingGraph(OccurrenceGraph):
            lookups = 0

            @staticmethod
            def _key(row, fields):
                CountingGraph.lookups += 1
                return OccurrenceGraph._key(row, fields)

        graph = CountingGraph(rows)
        self.assertEqual(500, len(graph.edges))
        self.assertLess(CountingGraph.lookups, 20 * len(rows))


if __name__ == "__main__":
    unittest.main()
