#!/usr/bin/env python3
"""Archive completed original-JUnit trials with per-file hashes."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
CAMPAIGN = EVIDENCE / "v3-campaign"
FILES = ("actor-events.tsv", "junit.log", "jacoco.exec", "manifest.json", "trial.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=int)
    parser.add_argument("last", type=int)
    args = parser.parse_args()
    if args.first < 1 or args.last < args.first:
        parser.error("expected a positive, increasing trial range")

    state = json.loads((CAMPAIGN / "state.json").read_text())
    assert len(state["attempts"]) >= args.last, "last trial is not checkpointed"
    stem = f"v3-campaign-r{args.first:03d}-r{args.last:03d}"
    archive = EVIDENCE / f"{stem}.tar.gz"
    manifest_path = EVIDENCE / f"{stem}-manifest.json"
    if archive.exists() or manifest_path.exists():
        raise FileExistsError(f"archive already exists: {stem}")
    temp_archive = archive.with_name(archive.name + ".tmp")
    items = []
    try:
        with tarfile.open(temp_archive, "w:gz", compresslevel=1) as tar:
            for number in range(args.first, args.last + 1):
                folder = f"r{number:03d}"
                trial = json.loads((CAMPAIGN / folder / "trial.json").read_text())
                manifest = json.loads((CAMPAIGN / folder / "manifest.json").read_text())
                assert trial["number"] == number == state["attempts"][number - 1]["number"]
                assert manifest["original_junit"] == "AddReplicaTest.testAddMultipleReplicas"
                assert manifest["original_source_commit"] == "e27f44e"
                for filename in FILES:
                    member = f"{folder}/{filename}"
                    raw = (CAMPAIGN / member).read_bytes()
                    info = tarfile.TarInfo(member)
                    info.size = len(raw)
                    info.mode = 0o644
                    info.mtime = 0
                    tar.addfile(info, io.BytesIO(raw))
                    items.append({"path": member, "bytes": len(raw),
                                  "sha256": hashlib.sha256(raw).hexdigest()})
        receipt = {"archive": archive.name, "archive_bytes": temp_archive.stat().st_size,
                   "archive_sha256": sha256_file(temp_archive), "case_id": "SOLR-19",
                   "file_count": len(items), "files": items, "first_trial": args.first,
                   "last_trial": args.last,
                   "original_junit": "AddReplicaTest.testAddMultipleReplicas",
                   "source_commit": "e27f44e"}
        temp_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
        temp_manifest.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        temp_archive.replace(archive)
        temp_manifest.replace(manifest_path)
        print(json.dumps({key: receipt[key] for key in ("archive", "archive_bytes",
                                                    "archive_sha256", "file_count",
                                                    "first_trial", "last_trial")}))
    finally:
        temp_archive.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
