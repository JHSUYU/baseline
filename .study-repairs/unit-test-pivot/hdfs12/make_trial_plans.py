"""Select HDFS-12 SERVER_READ faults only from GraphChecker target closure."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
TRACE = HERE / "server-door/record/healthy/trace"
OUTPUT = HERE / "server-door/trial-plans"
GUARD = ("<org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager: "
         "byte[] retrievePassword(org.apache.hadoop.hdfs.security.token.block."
         "BlockTokenIdentifier)>#u25")
ROOT_METHOD = "<org.apache.hadoop.hdfs.server.datanode.DataXceiver: void run()>"
ROOT_REGION = "REGION.61e62f41-34c6-3a5d-b610-b639dc3f4838"


def fuzzer_module():
    path = HERE.parent / "core-fuzzer/fuzzer.py"
    spec = importlib.util.spec_from_file_location("closure_fuzzer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    fuzzer = fuzzer_module()
    closure = fuzzer.read_closure(
        TRACE / "concolic_region_plan.jsonl", ROOT_METHOD,
        target_region_id=ROOT_REGION)
    if closure["blocking_gaps"] or len(closure["target_addresses"]) != 2:
        raise SystemExit("HDFS-12 closure has BLOCKING gaps or wrong target count")
    addresses = set(closure["addresses"])
    point_events = [row for row in fuzzer.rows(TRACE / "runtime_trace.jsonl")
                    if row.get("event") == "FAULT_POINT_OBSERVED"
                    and row.get("marker", "").startswith(
                        "FAULT:HDFS_SASL:SERVER_READ:")
                    and row.get("occurrenceAddress") in addresses]
    if len(point_events) != 4:
        raise SystemExit(f"expected four closure SERVER_READ points, got {len(point_events)}")
    by_request: dict[str, dict[str, dict]] = {}
    for row in point_events:
        address = row["occurrenceAddress"]
        if address not in closure["target_addresses"]:
            raise SystemExit("SERVER_READ marker is not in an exact target occurrence")
        request = address.split("/ctx:Root:DATANODE/DATA_XCEIVER#", 1)[1].split("/", 1)[0]
        kind = "eof" if "EOFException" in row["marker"] else "timeout"
        by_request.setdefault(request, {})[kind] = row
    if sorted(by_request) != ["4", "5"] or any(len(v) != 2 for v in by_request.values()):
        raise SystemExit(f"unexpected recorded DataXceiver requests: {by_request.keys()}")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    def selector(row: dict, fault_id: str) -> dict:
        return {"faultId": fault_id, "marker": row["marker"],
                "siteId": row["siteId"],
                "occurrence": row["occurrenceAddress"],
                "sourceKey": row["sourceKey"],
                "hitOrdinal": row["hitOrdinal"], "value": True}

    plans = {}
    for request, label in (("4", "first"), ("5", "second")):
        for kind in ("eof", "timeout"):
            name = f"{label}-{kind}"
            plans[name] = [selector(by_request[request][kind], name)]
    for first_kind in ("eof", "timeout"):
        for second_kind in ("eof", "timeout"):
            name = f"first-{first_kind}-then-second-{second_kind}"
            plans[name] = [
                selector(by_request["4"][first_kind], name + ":1"),
                selector(by_request["5"][second_kind], name + ":2"),
            ]
    for name, faults in plans.items():
        (OUTPUT / f"{name}.json").write_text(json.dumps({
            "schemaVersion": 1, "faults": faults,
            "targetSiteId": GUARD,
        }, indent=2) + "\n")
    (OUTPUT / "manifest.json").write_text(json.dumps({
        "sourceTrace": str(TRACE / "runtime_trace.jsonl"),
        "sourcePlan": str(TRACE / "concolic_region_plan.jsonl"),
        "targetAddresses": closure["target_addresses"],
        "closureAddresses": len(addresses),
        "blockingGaps": closure["blocking_gaps"],
        "serverReadPointsInClosure": len(point_events),
        "planNames": sorted(plans),
    }, indent=2) + "\n")
    print(json.dumps({"closureAddresses": len(addresses),
                      "blockingGaps": len(closure["blocking_gaps"]),
                      "pointsInClosure": len(point_events),
                      "plans": sorted(plans)}, indent=2))


if __name__ == "__main__":
    main()
