#!/usr/bin/env python3
"""Independent raw-receipt audit of the original-JUnit supplemental campaign."""

import argparse
from collections import Counter
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

import campaign


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
REMOTE_CASE = "/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-32"
SSH = ["ssh", "-i", str(Path.home() / ".ssh/id_ed25519_nodes"),
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "ZhenyuLi@node1"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def remote_bytes(path):
    return subprocess.run(SSH + ["cat", path], check=True,
                          stdout=subprocess.PIPE).stdout


def archived_segments():
    result = {}
    receipts = list(HERE.glob("evidence-segment-s*-s*-remote-receipt.json"))
    receipts += list(HERE.glob("evidence-v10-s114-s140-remote-receipt.json"))
    for receipt_file in receipts:
        receipt = json.loads(receipt_file.read_text())
        archive_path = receipt.get("archive", receipt.get("remote_archive"))
        archive_bytes = remote_bytes(archive_path)
        assert sha(archive_bytes) == receipt.get(
            "archive_sha256", receipt.get("remote_archive_sha256_verified"))
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
            for member in tar.getmembers():
                match = re.fullmatch(r"logs/(s\d+)\.log\.gz", member.name)
                if match:
                    assert match[1] not in result, match[1]
                    result[match[1]] = tar.extractfile(member).read()
    return result


def older_remote_path(trial_id):
    n = int(trial_id[1:])
    if n <= 47:
        folder = "upstream-archive-node0-s047/logs"
    elif n <= 80:
        folder = "archived-upstream/s048-s080"
    elif n <= 106:
        folder = "upstream-archive-node0-s106/logs"
    elif n <= 112:
        folder = "archive-node0-older-noncandidate-20261007/work-upstream/logs"
    else:
        raise FileNotFoundError(trial_id)
    return REMOTE_CASE + "/" + folder + "/" + trial_id + ".log.gz"


def log_bytes(trial, segments):
    path = CASE / trial["log"]
    if path.is_file():
        return path.read_bytes(), "local"
    if trial["id"] in segments:
        return segments[trial["id"]], "sha_archive_node1"
    return remote_bytes(older_remote_path(trial["id"])), "node1_old_raw"


def trace_from_bytes(trial_id, data):
    with tempfile.TemporaryDirectory(prefix="hbase32-audit-", dir="/dev/shm") as folder:
        path = Path(folder) / (trial_id + ".log.gz")
        path.write_bytes(data)
        return campaign.parse_log(path)


def run(through):
    state = json.loads(campaign.CHECKPOINT.read_text())
    trials = state["trials"][:through]
    assert [x["id"] for x in trials] == [f"s{i:03d}" for i in range(1, through + 1)]
    segments = archived_segments()
    source_counts = Counter()
    io_union = set(state["healthy_selectors"])
    admitted_execs = [str(HERE / "logs/healthy4.exec")]
    issues = []
    disposition_counts = Counter()
    for trial in trials:
        try:
            data, source = log_bytes(trial, segments)
            source_counts[source] += 1
            assert sha(data) == trial["compressed_log_sha256"]
            assert sha(gzip.decompress(data)) == trial["raw_log_sha256"]
            trace = trace_from_bytes(trial["id"], data)
            matched = campaign.strict(trace, trial["plan"])
            reached = campaign.target_outcome(trace, trial["plan"])
            aborts = {e["server"] for e in trace["RS_ABORT"] if
                      trace["shutdown_hook_line"] is None or
                      e["line"] < trace["shutdown_hook_line"]}
            invalid_cluster = matched and len(aborts) >= 3
            invalid_actor = (not campaign.same_plan_actor(trial["plan"]) or
                             (matched and not campaign.same_observed_actor(trace)))
            retained = bool(reached["method"] or reached["progress"] or reached["guard"])
            unexpected = matched and retained and not invalid_cluster and (
                trial["exit"] == 124 or trace["junit"] is not None and
                trace["junit"]["failed"] > 0)
            exec_path = HERE / "logs" / (trial["id"] + ".exec")
            exec_ok = exec_path.is_file() and exec_path.stat().st_size > 0
            admitted = (matched and retained and not invalid_cluster and
                        not invalid_actor and exec_ok and not unexpected)
            effective = admitted and bool(reached["b7"])
            assert matched == trial["strict"]
            assert invalid_cluster == trial["invalid_cluster"]
            # v10 left previously attempted, unmatched cross-actor plans in the
            # historical ledger. They have no admitted feedback and are not
            # queued again. Current trials and all admitted trials use the
            # exact raw-region/replica actor rule.
            assert (invalid_actor == trial["invalid_actor"] or
                    int(trial["id"][1:]) < 126 and not matched and
                    not trial["coverage_admitted"])
            assert retained == trial["target_retained"]
            assert bool(reached["b7"]) == trial["exact_b7"]
            assert trace["junit"] == trial["junit"]
            assert len(campaign.fault_events(trace)) == trial["applied_fault_events"]
            assert exec_ok and campaign.sha256(exec_path) == trial["exec_sha256"]
            assert trial["coverage_admitted"] == admitted
            assert trial["effective"] == effective
            assert int((HERE / "logs" / (trial["id"] + ".exit")).read_text()) == trial["exit"]
            if admitted:
                admitted_execs.append(str(exec_path))
                selectors = {x for _, x in campaign.selector_events(trace)}
                assert trial["new_io_selectors"] == len(selectors - io_union)
                io_union.update(selectors)
            disposition_counts[trial["disposition"]] += 1
        except Exception as e:
            issues.append({"trial": trial["id"], "error": repr(e)})
    if through == len(state["trials"]):
        if sorted(io_union) != state["io_union"]:
            issues.append({"feedback": "io_union_mismatch", "recomputed": len(io_union),
                           "checkpoint": len(state["io_union"])})
        if admitted_execs != state["coverage_execs"]:
            issues.append({"feedback": "coverage_execs_mismatch",
                           "recomputed": len(admitted_execs),
                           "checkpoint": len(state["coverage_execs"])})
        if not issues:
            coverage = campaign.coverage([Path(x) for x in admitted_execs])
            if coverage != state["coverage_union"]:
                issues.append({"feedback": "coverage_union_mismatch"})
    queue_plans = [";".join(x["plan"]) for x in state["queue"]]
    assert len(queue_plans) == len(set(queue_plans))
    assert all(campaign.same_plan_actor(x["plan"]) for x in state["queue"])
    result = {"through": through, "checkpoint_trials": len(state["trials"]),
              "effective": sum(x["effective"] for x in trials),
              "source_counts": dict(source_counts),
              "disposition_counts": dict(disposition_counts),
              "queue_length": len(state["queue"]), "issues": issues,
              "checkpoint_sha256": campaign.sha256(campaign.CHECKPOINT)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--through", type=int)
    args = parser.parse_args()
    state = json.loads(campaign.CHECKPOINT.read_text())
    raise SystemExit(run(args.through or len(state["trials"])))
