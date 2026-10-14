"""Verify imported native trials against their immutable predecessor evidence.

An imported trial may retain the predecessor's local-artifact manifest after
its raw directory has been archived.  The verifier checks both generations of
durable sidecars and every regular member of the archived raw tree.  It never
changes a campaign or extracts the archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _pinned(path: Any, digest: Any, label: str) -> Path:
    if (not isinstance(path, str) or not isinstance(digest, str) or
            not _DIGEST.fullmatch(digest)):
        raise ValueError(f"invalid {label} pin")
    candidate = Path(path)
    if (not candidate.is_absolute() or candidate.is_symlink() or
            not candidate.is_file() or _sha(candidate) != digest):
        raise ValueError(f"{label} bytes changed")
    return candidate


def _verified_archive(archive: Path, manifest: dict,
                      expected_source: str) -> dict[str, Any]:
    started = time.monotonic()
    rows = manifest.get("rows")
    if manifest.get("source") != expected_source or not isinstance(rows, list):
        raise ValueError("raw archive manifest has wrong source")
    expected: dict[str, tuple[int, str]] = {}
    for row in rows:
        name = row.get("path") if isinstance(row, dict) else None
        parts = PurePosixPath(name).parts if isinstance(name, str) else ()
        if (not parts or name.startswith("/") or ".." in parts or
                row.get("kind") not in ("file", "dir") or
                name in expected):
            raise ValueError("raw archive manifest has unsafe/duplicate member")
        if row["kind"] == "file":
            if (not isinstance(row.get("size"), int) or row["size"] < 0 or
                    not isinstance(row.get("sha256"), str) or
                    not _DIGEST.fullmatch(row["sha256"])):
                raise ValueError("raw archive manifest file pin is invalid")
            expected[name] = (row["size"], row["sha256"])
    if not expected:
        raise ValueError("raw archive manifest has no files")
    proc = subprocess.Popen(["zstd", "-dc", "--", str(archive)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    seen: set[str] = set()
    try:
        assert proc.stdout is not None
        with tarfile.open(fileobj=proc.stdout, mode="r|") as stream:
            for member in stream:
                name = member.name.removeprefix("./")
                parts = PurePosixPath(name).parts
                if (not parts or name.startswith("/") or ".." in parts or
                        member.issym() or member.islnk() or
                        not (member.isdir() or member.isfile())):
                    raise ValueError("raw archive has unsafe member")
                if member.isfile():
                    if name not in expected or name in seen:
                        raise ValueError("raw archive has unexpected/duplicate file")
                    size, digest = expected[name]
                    if member.size != size:
                        raise ValueError("raw archive member size changed")
                    source = stream.extractfile(member)
                    if source is None:
                        raise ValueError("raw archive member is unreadable")
                    actual = hashlib.sha256()
                    for block in iter(lambda: source.read(1 << 20), b""):
                        actual.update(block)
                    if actual.hexdigest() != digest:
                        raise ValueError("raw archive member bytes changed")
                    seen.add(name)
        if proc.wait(timeout=30) != 0 or seen != set(expected):
            raise ValueError("raw archive decompression/member set changed")
    finally:
        if proc.poll() is None:
            proc.kill()
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()
        proc.wait()
    return {"file_count": len(seen), "archive_bytes": archive.stat().st_size,
            "archive_sha256": _sha(archive),
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def _verify_local_manifest(local: dict, raw: dict) -> None:
    """Recompute the original campaign's local tree digest from raw pins."""
    source = raw["source"]
    prefix = Path(source).name + "/"
    selected_names = {
        "trace/streaming_trace_manifest.json", "trace/runtime_trace.jsonl",
        "trace/schedule.jsonl", "original-graph/summary.json",
        "stdout.log", "stderr.log",
    }
    files = sorted((row for row in raw["rows"] if row["kind"] == "file"),
                   key=lambda row: row["path"])
    digest = hashlib.sha256()
    selected: dict[str, str] = {}
    total_bytes = 0
    for row in files:
        if not row["path"].startswith(prefix):
            raise ValueError("raw manifest escaped local attempt directory")
        relative = row["path"][len(prefix):]
        digest.update(relative.encode() + b"\0F" + bytes.fromhex(row["sha256"]))
        total_bytes += row["size"]
        if relative in selected_names:
            selected[relative] = row["sha256"]
    if (local.get("file_count") != len(files) or
            local.get("total_bytes") != total_bytes or
            local.get("tree_sha256") != digest.hexdigest() or
            local.get("selected_sha256") != selected):
        raise ValueError("imported local manifest differs from archived raw tree")


def verify_import_lineage(native_root: Path, manifest_path: Path,
                          manifest_sha256: str) -> dict[str, Any]:
    """Check a pinned import map without modifying either campaign generation.

    A split archive must first be assembled and SHA-pinned as a regular file;
    the manifest may not silently substitute a remote or mutable stream.
    """
    pinned = _pinned(str(manifest_path), manifest_sha256, "import lineage")
    document = _object(pinned)
    if document.get("schema_version") != 1 or document.get("status") != "sealed":
        raise ValueError("import lineage is not sealed")
    checkpoint = native_root / "checkpoint.json"
    summary = native_root / "summary.json"
    if (_sha(checkpoint) != document.get("checkpoint_sha256") or
            _sha(summary) != document.get("summary_sha256") or
            document.get("campaign_root") != str(native_root.resolve())):
        raise ValueError("import lineage campaign changed")
    if "source_audit_path" in document or "source_audit_sha256" in document:
        _pinned(document.get("source_audit_path"),
                document.get("source_audit_sha256"), "source import audit")
    checkpoint_data = _object(checkpoint)
    refs = [checkpoint_data.get("healthy"), *checkpoint_data.get("trials", [])]
    admitted = {ref.get("name") for ref in refs if isinstance(ref, dict) and
                ref.get("result") == f"trials/{ref.get('name')}/result.json"}
    imported = document.get("imports")
    if not isinstance(imported, list) or not imported:
        raise ValueError("import lineage has no trials")
    evidence: dict[str, Any] = {}
    seen: set[str] = set()
    for entry in imported:
        name = entry.get("trial") if isinstance(entry, dict) else None
        if (not isinstance(name, str) or not re.fullmatch(r"r\d{4}", name) or
                name in seen or name not in admitted):
            raise ValueError("import lineage trial identity is invalid")
        seen.add(name)
        source_root = Path(entry.get("predecessor_trial", ""))
        target_root = native_root / "trials" / name
        if (not source_root.is_absolute() or source_root.is_symlink() or
                source_root.name != name or not target_root.is_dir()):
            raise ValueError("import predecessor or destination changed")
        copied = entry.get("copied")
        omitted = entry.get("omitted")
        if not isinstance(copied, dict) or not copied or not isinstance(omitted, dict):
            raise ValueError("import sidecar map is invalid")
        for relative, digest in copied.items():
            if (not isinstance(relative, str) or relative.startswith("/") or
                    ".." in PurePosixPath(relative).parts):
                raise ValueError("import copied sidecar path is unsafe")
            _pinned(str(source_root / relative), digest, "predecessor sidecar")
            _pinned(str(target_root / relative), digest, "imported sidecar")
        if "result.json" not in copied or "local-artifacts.json" not in copied:
            raise ValueError("import lacks result/local manifest identity")
        for relative, digest in omitted.items():
            if (not isinstance(relative, str) or relative.startswith("/") or
                    ".." in PurePosixPath(relative).parts or
                    relative in copied or (target_root / relative).exists()):
                raise ValueError("import omitted sidecar path is invalid")
            _pinned(str(source_root / relative), digest, "omitted predecessor sidecar")
        archive = _pinned(entry.get("archive"), entry.get("archive_sha256"),
                          "predecessor raw archive")
        raw_manifest_path = _pinned(entry.get("raw_manifest"),
                                    entry.get("raw_manifest_sha256"),
                                    "predecessor raw manifest")
        raw_receipt_path = _pinned(entry.get("raw_receipt"),
                                   entry.get("raw_receipt_sha256"),
                                   "predecessor raw receipt")
        receipt = _object(raw_receipt_path)
        raw = _object(raw_manifest_path)
        local = _object(target_root / "local-artifacts.json")
        if (receipt.get("status") != "source_reclaimed_verified" or
                receipt.get("source") != raw.get("source") or
                receipt.get("result_sha256") != copied["result.json"] or
                receipt.get("manifest_sha256") != entry["raw_manifest_sha256"] or
                receipt.get("archive_sha256") != entry["archive_sha256"] or
                local.get("local_attempt_dir") != raw.get("source") or
                local.get("campaign_root") != str(source_root.parent.parent)):
            raise ValueError("predecessor raw receipt/local manifest differs")
        _verify_local_manifest(local, raw)
        archive_result = _verified_archive(archive, raw, receipt["source"])
        evidence[name] = {"copied": copied, "omitted": omitted,
                          "raw_archive": archive_result,
                          "raw_manifest_sha256": entry["raw_manifest_sha256"]}
    return {"schema_version": 1, "method": "pinned_predecessor_full_raw_import",
            "campaign_root": str(native_root.resolve()),
            "checkpoint_sha256": document["checkpoint_sha256"],
            "summary_sha256": document["summary_sha256"],
            "manifest_sha256": manifest_sha256, "imports": evidence}


def verify_import_evidence(native_root: Path, pin: dict[str, str],
                           case_id: str) -> dict[str, Any]:
    """Recheck imported raw and graph receipts through a sealed descriptor.

    The expensive archive stream is intentional: an imported trial may have
    released its original local scratch.  Neither a predecessor result nor an
    archived graph summary is accepted merely because its metadata matches.
    """
    if not isinstance(pin, dict) or set(pin) != {"path", "sha256"}:
        raise ValueError("import evidence pin is invalid")
    descriptor = _object(_pinned(pin["path"], pin["sha256"],
                                 "import evidence descriptor"))
    required = {"schema_version", "case_id", "native_root",
                "lineage_path", "lineage_sha256", "verified_path",
                "verified_sha256", "graph_path", "graph_sha256",
                "auxiliary_java_path", "auxiliary_java_sha256",
                "auxiliary_java_commit"}
    if (set(descriptor) != required or descriptor["schema_version"] != 1 or
            descriptor["case_id"] != case_id or
            descriptor["native_root"] != str(native_root.resolve())):
        raise ValueError("import evidence descriptor identity changed")
    lineage_path = _pinned(descriptor["lineage_path"],
                           descriptor["lineage_sha256"], "import lineage")
    _pinned(descriptor["auxiliary_java_path"],
            descriptor["auxiliary_java_sha256"], "original Java plan helper")
    if (not isinstance(descriptor["auxiliary_java_commit"], str) or
            len(descriptor["auxiliary_java_commit"]) < 8):
        raise ValueError("original Java plan helper lacks source commit")
    prior = _object(_pinned(descriptor["verified_path"],
                            descriptor["verified_sha256"],
                            "prior full import validation"))
    current = verify_import_lineage(native_root, lineage_path,
                                    descriptor["lineage_sha256"])
    # Archive validation elapsed depends on disk/cache state.  Every identity,
    # file count, member digest, and tree digest must still match exactly.
    for receipt in (prior, current):
        for item in receipt["imports"].values():
            item["raw_archive"].pop("elapsed_seconds", None)
    if current != prior:
        raise ValueError("imported raw/sidecar validation differs from seal")
    graph = _object(_pinned(descriptor["graph_path"],
                            descriptor["graph_sha256"],
                            "imported graph receipt index"))
    names = set(current["imports"])
    if (graph.get("schema_version") != 1 or
            graph.get("lineage_sha256") != descriptor["lineage_sha256"] or
            not isinstance(graph.get("graph_receipts"), dict) or
            set(graph["graph_receipts"]) != names):
        raise ValueError("imported graph receipt set differs from lineage")
    graph_lineage_sha = descriptor["lineage_sha256"]
    if "prior_lineage_sha256" in graph:
        keys = {"schema_version", "lineage_sha256", "graph_receipts",
                "prior_lineage_path", "prior_lineage_sha256",
                "relocation_receipt_path", "relocation_receipt_sha256"}
        if set(graph) != keys:
            raise ValueError("imported graph relocation schema changed")
        prior_lineage = _object(_pinned(
            graph["prior_lineage_path"], graph["prior_lineage_sha256"],
            "prior graph-replay lineage"))
        relocation = _object(_pinned(
            graph["relocation_receipt_path"],
            graph["relocation_receipt_sha256"],
            "archive relocation receipt"))
        current_lineage = _object(lineage_path)
        before = {row["trial"]: row for row in prior_lineage["imports"]}
        after = {row["trial"]: row for row in current_lineage["imports"]}
        if set(before) != set(after) or set(after) != names:
            raise ValueError("graph-replay lineage changed trial membership")
        relocated = []
        for name in sorted(names):
            old, new = before[name], after[name]
            normalized = dict(new)
            normalized["archive"] = old["archive"]
            if normalized != old:
                raise ValueError("graph-replay lineage changed beyond archive path")
            if new["archive"] != old["archive"]:
                relocated.append((old["archive"], new["archive"],
                                  new["archive_sha256"]))
        normalized_doc = dict(current_lineage)
        normalized_doc["imports"] = prior_lineage["imports"]
        if (normalized_doc != prior_lineage or len(relocated) != 1 or
                relocation.get("method") !=
                    "byte_identical_combined_archive_relocation" or
                (relocation.get("source"), relocation.get("destination"),
                 relocation.get("sha256")) != relocated[0]):
            raise ValueError("graph-replay archive relocation is unproved")
        graph_lineage_sha = graph["prior_lineage_sha256"]
    elif set(graph) != {"schema_version", "lineage_sha256", "graph_receipts"}:
        raise ValueError("imported graph index schema changed")
    for name, row in graph["graph_receipts"].items():
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise ValueError("imported graph receipt pin is invalid")
        receipt = _object(_pinned(row["path"], row["sha256"],
                                  "imported graph recomputation"))
        source = Path(next(entry["predecessor_trial"] for entry in
                           _object(lineage_path)["imports"]
                           if entry["trial"] == name))
        if (receipt.get("trial") != name or
                receipt.get("lineage_sha256") != graph_lineage_sha or
                receipt.get("result_sha256") != _sha(source / "result.json")):
            raise ValueError("imported graph receipt differs from source result")
        summary = source / "native-summary.json"
        if summary.is_file():
            if (receipt.get("status") != "verified" or
                    receipt.get("native_summary_sha256") != _sha(summary) or
                    receipt.get("computed", {}).get("summary_sha256") !=
                        _sha(summary)):
                raise ValueError("imported graph recomputation is incomplete")
        elif receipt.get("status") != "no_graph_unmatched":
            raise ValueError("missing imported graph has wrong verdict")
    return {"descriptor": pin, "imported_trials": sorted(names),
            "lineage_sha256": descriptor["lineage_sha256"],
            "verified_sha256": descriptor["verified_sha256"],
            "graph_sha256": descriptor["graph_sha256"],
            "auxiliary_java_sha256": descriptor["auxiliary_java_sha256"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("import lineage output already exists")
    receipt = verify_import_lineage(args.native_root, args.manifest,
                                   args.manifest_sha256)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
