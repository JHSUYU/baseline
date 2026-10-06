"""Extract the observed local map history from the original HDFS-11 seed.

This reports runtime correspondence only; it does not add a GraphChecker edge.
"""

from collections import defaultdict
from pathlib import Path
import argparse
import json


HERE = Path(__file__).resolve().parent
TRACE = HERE / "healthy-final/trace/runtime_trace.jsonl"
OUTPUT = HERE / "key-state-evidence.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, default=TRACE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    trace_path = args.trace.resolve()
    output_path = args.output.resolve()
    rows = [json.loads(line) for line in trace_path.open()]
    by_invocation = defaultdict(list)
    managers = {}
    boxed_ints = {}
    for row in rows:
        invocation = row.get("invocationId", 0)
        if invocation:
            by_invocation[invocation].append(row)
        if row["event"] == "METHOD_ENTER":
            managers[row.get("callId")] = row.get("objectId")
    for invocation, events in by_invocation.items():
        if not any(e.get("declaredCallee", "").startswith(
                "<java.lang.Integer: java.lang.Integer valueOf(int)>")
                for e in events):
            continue
        arg = next((e for e in events if e["event"] == "CALL_ARGUMENT"
                    and e.get("argumentIndex") == 0), None)
        ret = next((e for e in events if e["event"] == "CALL_SITE_RETURN"), None)
        if arg and ret and ret.get("objectId"):
            boxed_ints[ret["objectId"]] = int(arg["primitiveValue"])

    operations = []
    for invocation, events in by_invocation.items():
        enter = next((e for e in events if e["event"] == "CALL_SITE_ENTER"), None)
        ret = next((e for e in events if e["event"] == "CALL_SITE_RETURN"), None)
        if not enter or not ret:
            continue
        callee = enter.get("declaredCallee", "")
        if not any(s in callee for s in (
                "<java.util.Map: java.lang.Object put(",
                "<java.util.Map: java.lang.Object get(",
                "<java.util.Map: java.lang.Object remove(",
                "<java.util.Map: void clear()>",
        )):
            continue
        method = enter.get("method", "")
        if "BlockTokenSecretManager:" not in method:
            continue
        args = {e.get("argumentIndex"): e for e in events
                if e["event"] == "CALL_ARGUMENT"}
        key_obj = args.get(0, {}).get("objectId")
        val_obj = args.get(1, {}).get("objectId")
        operations.append({
            "op": "put" if " put(" in callee else
                  "get" if " get(" in callee else
                  "remove" if " remove(" in callee else "clear",
            "enterSeq": enter["seq"],
            "returnSeq": ret["seq"],
            "siteId": enter.get("siteId"),
            "managerObjectId": managers.get(enter.get("callId")),
            "mapObjectId": enter.get("objectId"),
            "keyObjectId": key_obj,
            "keyId": boxed_ints.get(key_obj),
            "writtenValueObjectId": val_obj,
            "returnedValueObjectId": ret.get("objectId"),
        })

    target_gets = [x for x in operations if x["op"] == "get"
                   and "retrieveDataEncryptionKey" in x["siteId"]]
    if len(target_gets) != 2 or any(x["keyId"] is None for x in target_gets):
        raise AssertionError(f"unexpected target gets: {target_gets}")
    matched_puts = []
    for get in target_gets:
        prior = [x for x in operations if x["op"] == "put"
                 and x["returnSeq"] < get["enterSeq"]
                 and (x["managerObjectId"], x["mapObjectId"], x["keyId"])
                 == (get["managerObjectId"], get["mapObjectId"], get["keyId"])]
        if not prior:
            raise AssertionError(f"no observed prior put: {get}")
        put = prior[-1]
        if put["writtenValueObjectId"] != get["returnedValueObjectId"]:
            raise AssertionError(f"put/get value mismatch: {put}, {get}")
        matched_puts.append(put)
    relevant_mutations = [x for x in operations
                          if x["op"] in ("remove", "clear")
                          and x["mapObjectId"] == target_gets[0]["mapObjectId"]
                          and matched_puts[0]["returnSeq"] < x["enterSeq"]
                          < target_gets[-1]["enterSeq"]]
    if relevant_mutations:
        raise AssertionError(f"intervening map mutation: {relevant_mutations}")
    result = {
        "trace": str(trace_path),
        "interpretation": "Observed same local map, integer key, and BlockKey value; GraphChecker edgeEvidence remains UNAVAILABLE.",
        "matchedPut": matched_puts[0],
        "targetGets": target_gets,
        "interveningRemoveOrClearCallSites": relevant_mutations,
        "allObservedManagerMapCalls": operations,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    print(output_path)


if __name__ == "__main__":
    main()
