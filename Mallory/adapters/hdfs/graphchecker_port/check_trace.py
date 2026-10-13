#!/usr/bin/env python3
"""Check the actual request/response causal path of the unchanged HDFS JUnit."""

import json
import sys
from collections import Counter
from pathlib import Path


def check(trace_file: Path) -> None:
    # A full static-scope trial can produce millions of coverage rows. Only
    # retain the request/response handoffs needed by this protocol check.
    row_count = 0
    gap_count = 0
    scope_unbalanced = False
    rows = []
    with trace_file.open() as trace:
        for line in trace:
            row_count += 1
            if '"kind":"GAP"' in line:
                gap_count += 1
                if json.loads(line).get("gapKind") == "SCOPE_UNBALANCED":
                    scope_unbalanced = True
            elif any(f'"kind":"{kind}"' in line for kind in
                     ("EXPORT", "ATTACH", "SCOPE_ENTER")):
                rows.append(json.loads(line))
    assert row_count, "empty trace"
    assert not scope_unbalanced, "request scope stack was not restored"
    exports = Counter(row.get("producerEndpointId") for row in rows
                      if row.get("kind") == "EXPORT")
    assert all(exports[row.get("producerEndpointId")] == 1 for row in rows
               if row.get("kind") == "ATTACH"), (
        "an attached wire endpoint has zero or multiple matching exports"
    )

    seen = set()
    for force in ("false", "true"):
        api = f"DFSAdmin.deleteBlockPool(force={force})"
        scopes = [row for row in rows if row.get("kind") == "SCOPE_ENTER"
                  and row.get("api") == api]
        assert len(scopes) == 1, f"expected one original {api} request root"
        requests = [row for row in rows if row.get("kind") == "EXPORT"
                    and row.get("half") == "REQUEST"
                    and (f"/{api}#" in row.get("occurrence", "")
                         or f"/{api}#" in row.get("producer", ""))]
        assert len(requests) == 1, f"expected one outbound request from {api}"
        request = requests[0]
        identity = (request["correlationId"], request["attemptId"])
        assert identity not in seen, "different commands reused one RPC identity"
        seen.add(identity)
        assert request["node"].startswith("dfsadmin#")

        def matching(kind: str, half: str):
            found = [row for row in rows if row.get("kind") == kind
                     and row.get("half") == half
                     and (row.get("correlationId"), row.get("attemptId")) == identity]
            assert len(found) == 1, f"expected one {kind} {half} for {identity}"
            return found[0]

        server_receive = matching("ATTACH", "REQUEST")
        server_send = matching("EXPORT", "RESPONSE")
        client_receive = matching("ATTACH", "RESPONSE")
        assert server_receive["node"].startswith("dn0#")
        assert server_send["node"].startswith("dn0#")
        assert client_receive["node"].startswith("dfsadmin#")
        assert request["producerEndpointId"] == server_receive["producerEndpointId"]
        assert server_send["producerEndpointId"] == client_receive["producerEndpointId"]
        assert (request["seq"] < server_receive["seq"] < server_send["seq"]
                < client_receive["seq"]), "causal handoffs out of order"

    print("TRACE_CHECK=PASS original JUnit generated two distinct DFSAdmin roots "
          "with exact request and response IPC handoffs")
    print(f"TRACE_ROWS={row_count} GAPS={gap_count}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_trace.py <trace.jsonl>")
    check(Path(sys.argv[1]))
