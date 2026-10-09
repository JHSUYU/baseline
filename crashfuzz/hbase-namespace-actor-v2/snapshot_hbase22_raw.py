#!/usr/bin/env python3
"""Archive an immutable completed HBASE-22 prefix without touching live runs."""
import hashlib
import io
import json
import tarfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
CHECKPOINT = HERE / "campaigns/HBASE-22/checkpoint.json"
EVIDENCE = HERE / "evidence/HBASE-22"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    content = CHECKPOINT.read_bytes()
    state = json.loads(content)
    attempts = len(state["trials"])
    prefix = "checkpoint-snapshot-r%03d" % attempts
    archive = EVIDENCE / (prefix + ".tar.gz")
    manifest_path = EVIDENCE / (prefix + ".receipt.json")
    if archive.exists() or manifest_path.exists():
        raise RuntimeError("Snapshot already exists")
    files = {"campaigns/HBASE-22/checkpoint.json": content}
    for seed in state["healthy_seeds"]:
        directory = HERE / "runs" / ("table-" + seed)
        for name in ("healthy.log", "healthy.exit", "healthy.plan", "healthy.exec", "agent.sha256"):
            path = directory / name
            if path.is_file():
                files[str(path.relative_to(HERE))] = path.read_bytes()
    for trial in state["trials"]:
        directory = HERE / trial["raw_run"]
        for name in ("trial.log", "trial.exit", "trial.plan", "agent.sha256"):
            path = directory / name
            if not path.is_file():
                raise RuntimeError("Missing completed raw receipt: " + str(path))
            files[str(path.relative_to(HERE))] = path.read_bytes()
        path = directory / "trial.exec"
        if path.is_file():
            files[str(path.relative_to(HERE))] = path.read_bytes()
    manifest = {"attempts": attempts, "effective": state["effective"],
                "checkpoint_sha256": sha(content),
                "files": {name: sha(value) for name, value in files.items()}}
    with tarfile.open(archive, "w:gz") as tar:
        for name, value in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(value)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(value))
    # Re-read the archive to catch a truncated gzip or mismatched entries.
    with tarfile.open(archive, "r:gz") as tar:
        observed = {member.name: sha(tar.extractfile(member).read())
                    for member in tar.getmembers() if member.isfile()}
    if observed != manifest["files"]:
        raise RuntimeError("Archive verification failed")
    manifest["archive_sha256"] = sha(archive.read_bytes())
    manifest["archive_bytes"] = archive.stat().st_size
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: manifest[key] for key in
                      ("attempts", "effective", "checkpoint_sha256", "archive_sha256", "archive_bytes")}))


if __name__ == "__main__":
    main()
