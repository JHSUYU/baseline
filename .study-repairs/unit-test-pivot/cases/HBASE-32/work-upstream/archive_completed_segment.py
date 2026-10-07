#!/usr/bin/env python3
"""Mirror immutable HBASE-32U trial receipts to node1 before local log offload."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
REMOTE = "ZhenyuLi@node1"
SSH = ["ssh", "-i", str(Path.home() / ".ssh/id_ed25519_nodes"),
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", REMOTE]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("start", type=int)
    p.add_argument("end", type=int)
    p.add_argument("--offload-logs", action="store_true")
    args = p.parse_args()
    assert 1 <= args.start <= args.end
    label = f"s{args.start:03d}-s{args.end:03d}"
    manifest_path = HERE / f"evidence-segment-{label}-manifest.json"
    receipt_path = HERE / f"evidence-segment-{label}-remote-receipt.json"
    offload_path = HERE / f"evidence-segment-{label}-offload-receipt.json"
    stage = CASE / f"upstream-segment-{label}"

    state = json.loads((HERE / "supplemental-checkpoint.json").read_text())
    selected = state["trials"][args.start - 1:args.end]
    assert len(selected) == args.end - args.start + 1
    assert [t["id"] for t in selected] == [f"s{i:03d}" for i in range(args.start, args.end + 1)]
    if any(t.get("review_candidate") or t["disposition"] in
           {"timeout_requires_review", "junit_failure_requires_review"} for t in selected):
        raise RuntimeError("Segment contains a candidate under review")

    files = []
    for t in selected:
        for ext in ("log.gz", "exec", "exit"):
            rel = f"logs/{t['id']}.{ext}"
            path = HERE / rel
            if not path.is_file():
                raise RuntimeError(f"Missing local receipt: {path}")
            files.append({"path": rel, "bytes": path.stat().st_size,
                          "sha256": digest(path)})
    manifest = {"segment": label, "files": files,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "checkpoint_trial_count": len(state["trials"]),
                "checkpoint_effective": sum(t["effective"] for t in state["trials"]),
                "agent_source_sha256": digest(HERE / "src" / "HBase32UpstreamAgent.java"),
                "agent_jar_sha256": digest(HERE / "agent.jar")}
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if old["files"] != files:
            raise RuntimeError("Existing segment manifest differs from local receipts")
    else:
        atomic_json(manifest_path, manifest)

    subprocess.run(SSH + ["mkdir -p " + str(stage / "files")], check=True)
    filelist = HERE / f"evidence-segment-{label}-filelist.txt"
    filelist.write_text("".join(f["path"] + "\n" for f in files))
    subprocess.run(["rsync", "-a", "-e", "ssh -i " +
                    str(Path.home() / ".ssh/id_ed25519_nodes") +
                    " -o IdentitiesOnly=yes -o BatchMode=yes",
                    "--files-from=" + str(filelist), str(HERE) + "/",
                    REMOTE + ":" + str(stage / "files") + "/"], check=True)
    subprocess.run(["rsync", "-a", "-e", "ssh -i " +
                    str(Path.home() / ".ssh/id_ed25519_nodes") +
                    " -o IdentitiesOnly=yes -o BatchMode=yes",
                    str(manifest_path), REMOTE + ":" + str(stage / "manifest.json")],
                   check=True)

    remote_code = r'''
import hashlib, json, pathlib, tarfile
root = pathlib.Path("REMOTE_STAGE")
manifest = json.loads((root / "manifest.json").read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
for item in manifest["files"]:
    p=root / "files" / item["path"]
    assert p.stat().st_size == item["bytes"] and sha(p) == item["sha256"], item["path"]
archive=root / (manifest["segment"] + ".tar.gz")
with tarfile.open(archive,"w:gz") as tar:
    tar.add(root / "manifest.json",arcname="manifest.json")
    for item in manifest["files"]:
        tar.add(root / "files" / item["path"],arcname=item["path"])
with tarfile.open(archive,"r:gz") as tar:
    assert set(tar.getnames()) == {"manifest.json"} | {x["path"] for x in manifest["files"]}
    for item in manifest["files"]:
        h=hashlib.sha256()
        f=tar.extractfile(item["path"])
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
        assert h.hexdigest() == item["sha256"],item["path"]
receipt={"segment":manifest["segment"],"archive":str(archive),
         "archive_sha256":sha(archive),"members_verified":len(manifest["files"]),
         "manifest_sha256":sha(root / "manifest.json")}
(root / "remote-receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
print(json.dumps(receipt,sort_keys=True))
'''.replace("REMOTE_STAGE", str(stage))
    result = subprocess.run(SSH + ["python3 -"], input=remote_code,
                            text=True, capture_output=True, check=True)
    receipt = json.loads(result.stdout.strip())
    assert receipt["members_verified"] == len(files)
    atomic_json(receipt_path, receipt)
    if args.offload_logs:
        archived = []
        for t in selected:
            rel = f"logs/{t['id']}.log.gz"
            item = next(x for x in files if x["path"] == rel)
            path = HERE / rel
            if digest(path) != item["sha256"]:
                raise RuntimeError("Local log changed before offload: " + rel)
            path.unlink()
            archived.append(item)
        atomic_json(offload_path, {"segment": label, "remote_archive": receipt["archive"],
                                   "remote_archive_sha256": receipt["archive_sha256"],
                                   "files_offloaded": archived,
                                   "jacoco_and_exit_receipts_local": True})
    print(json.dumps({"segment": label, "files": len(files),
                      "archive_sha256": receipt["archive_sha256"],
                      "logs_offloaded": len(selected) if args.offload_logs else 0}))


if __name__ == "__main__":
    main()
