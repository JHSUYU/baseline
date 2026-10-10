#!/usr/bin/env python3
"""Read-only HDFS-48 audit pin and source-anchor check; launches no JVM."""

import hashlib
import gzip
import json
import subprocess
from pathlib import Path


here = Path(__file__).resolve().parent
receipt = json.loads((here / "source-receipt.json").read_text())
assert receipt["case_id"] == "HDFS-48"
assert receipt["source_commit"] == subprocess.check_output(
    ["git", "-C", receipt["source_root"], "rev-parse", "HEAD"], text=True
).strip()

for artifact in receipt["artifacts"]:
    path = Path(artifact["path"])
    assert path.is_file(), path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"], path

source = {
    Path(a["path"]).name: Path(a["path"]).read_text()
    for a in receipt["artifacts"]
    if a["group"] == "source"
}
assert "Preconditions.checkState(oldChild == children.get(i)" in source["INodeDirectory.java"]
assert "replaceChild4ReferenceWithName(srcChild, srcLatestSnapshotId)" in source["FSDirRenameOp.java"]
assert "if (isSrcInSnapshot)" in source["FSDirRenameOp.java"]
assert "if (success) {\n      getEditLog().logSync();" in source["FSNamesystem.java"]
assert "value = call(" in source["Server.java"]
assert "catch (Throwable e)" in source["Server.java"]
assert "ByteBuffer bb = ipcStreams.readResponse();" in source["Client.java"]
assert "int length = in.readInt();" in source["Client.java"]
assert "in.readFully(bb.array());" in source["Client.java"]
assert "} catch (IOException e) {\n        markClosed(e);" in source["Client.java"]
assert "} catch (IOException e) {\n        LOG.warn(\"IOException in offerService\"" in source["BPServiceActor.java"]
assert "boolean POLICY_ENABLED_DEFAULT = false;" in source["HdfsClientConfigKeys.java"]
assert "public void testRenameUndo_1()" in source["TestRenameWithSnapshots.java"]
assert "root.replaceChild(dir2, mockDir2, fsdir.getINodeMap());" in source["TestRenameWithSnapshots.java"]
assert "this.renamed = client.rename(oldName, newName);" in source["TestRetryCacheWithHA.java"]
assert "client.renameSnapshot(dir, oldName, newName);" in source["TestRetryCacheWithHA.java"]

archived = json.loads(Path(next(
    a["path"] for a in receipt["artifacts"]
    if a["path"].endswith("calibration_v14_node0/HDFS-48/result.json")
)).read_text())
assert archived["trials"][0]["junit_status"] == "passed"
assert archived["trials"][0]["target_reached"] is True
trace_path = Path(next(
    a["path"] for a in receipt["artifacts"]
    if a["path"].endswith("calibration_v14_node0/HDFS-48/trials/r0000/events.jsonl.gz")
))
with gzip.open(trace_path, "rt") as trace:
    selected = {
        event["seq"]: event
        for event in (json.loads(line) for line in trace)
        if event.get("seq") in (2587, 2788)
    }
assert set(selected) == {2587, 2788}
assert selected[2587]["node"] == "hdfs-client"
assert selected[2788]["node"] == "hdfs-cluster-1/nn0"
assert all(e["type"] == "TARGET_CHECK" and e["outcome"] == "TAKEN"
           and e["site"].endswith("@356:branch:2") for e in selected.values())
pilot = json.loads(Path(next(
    a["path"] for a in receipt["artifacts"]
    if a["path"].endswith("pilots_v14/HDFS-48-nn-only/result.json")
)).read_text())
faults = [trial for trial in pilot["trials"] if trial["trial_id"] != 0]
assert len(faults) == 10
assert all(t["all_faults_effective"] and not t["target_reached"] for t in faults)
actor = json.loads(Path(next(
    a["path"] for a in receipt["artifacts"]
    if a["path"].endswith("heartbeat-actor-audit.json")
)).read_text())
assert actor["actor_joined_heartbeat_trials"] == 107
assert len(actor["admitted_trial_ids"]) == 107

print(json.dumps({
    "status": "source_reaudit_pass",
    "case_id": "HDFS-48",
    "pinned_artifacts": len(receipt["artifacts"]),
    "archived_ingress_faults_lost_target": len(faults),
    "historical_heartbeat_actor_joined_trials": actor["actor_joined_heartbeat_trials"],
    "jvm_launched": False,
    "fault_or_full_admitted": False,
}, sort_keys=True))
