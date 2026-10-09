#!/usr/bin/env python3
"""Stage bounded, reviewable evidence from one completed worker case.

The full case directory stays on its worker.  Node0 rsyncs only this staging
directory and records the source paths and SHA-256 hashes in its manifest.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import socket
import sys
import uuid
from pathlib import Path


JSON_NAMES = {"result.json", "state.json", "fault-trial.json", "plan.json",
              "manifest.json", "summary.json", "targets.json",
              "streaming_trace_manifest.json"}
TRACE_NAMES = {"runtime_trace.jsonl", "concolic_region_plan.jsonl",
               "plan.jsonl", "schedule.jsonl"}
MAX_FILES = 5000
MAX_JSON_BYTES = 4 * 1024 * 1024


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidates(case_dir: Path):
    roots = [case_dir, case_dir / "trials", case_dir / "seed-command",
             case_dir / ".coord"]
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for directory, names, files in os.walk(root, followlinks=False):
            relative_directory = Path(directory).relative_to(case_dir)
            names[:] = [name for name in names
                        if name not in {"temp", "tmp", "worktrees", "build",
                                        "target", ".git", "node_modules"} and
                        not (relative_directory == Path(".coord") and
                             name.startswith("evidence-"))]
            if root == case_dir:
                # The other roots are scanned separately; avoid walking
                # whole system workspaces accidentally placed below a case.
                names[:] = []
            for name in sorted(files):
                path = Path(directory) / name
                if path in seen or path.is_symlink() or not path.is_file():
                    continue
                seen.add(path)
                if name in JSON_NAMES or name in TRACE_NAMES or name.endswith(".log"):
                    yield path


def stage(case_dir: Path, stage_dir: Path, profile: str, max_bytes: int,
          log_tail_bytes: int) -> dict:
    case_dir = case_dir.resolve()
    stage_dir = stage_dir.resolve()
    if not case_dir.is_dir() or case_dir not in stage_dir.parents or \
            stage_dir.parent != case_dir / ".coord":
        raise ValueError("stage must be a direct child of the case's .coord directory")
    if profile not in {"summary", "trace"} or max_bytes < 1024 * 1024:
        raise ValueError("profile must be summary or trace; budget at least 1 MiB")
    stage_dir.mkdir(parents=True, exist_ok=True)
    reserve = min(2 * 1024 * 1024, max_bytes // 4)
    data_budget = max_bytes - reserve
    used = 0
    selected: list[dict] = []
    omitted: list[dict] = []
    count = 0
    for src in candidates(case_dir):
        count += 1
        if count > MAX_FILES:
            omitted.append({"reason": "file_count_limit", "limit": MAX_FILES})
            break
        rel = src.relative_to(case_dir)
        size = src.stat().st_size
        source = {"relative_path": rel.as_posix(), "source_path": str(src),
                  "source_bytes": size, "source_sha256": hash_file(src)}
        is_trace = src.name in TRACE_NAMES
        if is_trace and profile == "summary":
            omitted.append({**source, "reason": "profile_summary"})
            continue
        remaining = data_budget - used
        if remaining <= 0:
            omitted.append({**source, "reason": "byte_budget"})
            continue
        if is_trace:
            dest = stage_dir / (rel.as_posix() + ".gz")
            dest.parent.mkdir(parents=True, exist_ok=True)
            temporary = dest.with_name(dest.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                with temporary.open("wb") as raw, gzip.GzipFile(
                        filename="", fileobj=raw, mode="wb", mtime=0) as compressed, \
                        src.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        compressed.write(chunk)
                        if raw.tell() > remaining:
                            raise OverflowError("compressed trace exceeds byte budget")
                staged_size = temporary.stat().st_size
                if staged_size > remaining:
                    raise OverflowError("compressed trace exceeds byte budget")
                os.replace(temporary, dest)
            except OverflowError:
                temporary.unlink(missing_ok=True)
                omitted.append({**source, "reason": "compressed_trace_budget"})
                continue
            kind = "compressed_trace"
            truncated = False
        else:
            is_log = src.name.endswith(".log")
            limit = min(log_tail_bytes if is_log else MAX_JSON_BYTES, remaining)
            if not is_log and size > limit:
                omitted.append({**source, "reason": "json_byte_budget"})
                continue
            if limit <= 0:
                omitted.append({**source, "reason": "byte_budget"})
                continue
            dest = stage_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            temporary = dest.with_name(dest.name + "." + uuid.uuid4().hex + ".tmp")
            with src.open("rb") as stream, temporary.open("wb") as output:
                if is_log and size > limit:
                    stream.seek(-limit, os.SEEK_END)
                shutil.copyfileobj(stream, output)
            os.replace(temporary, dest)
            staged_size = dest.stat().st_size
            kind = "log_tail" if is_log and size > staged_size else (
                "log" if is_log else "json")
            truncated = staged_size < size
        used += staged_size
        selected.append({**source, "staged_path": dest.relative_to(stage_dir).as_posix(),
                         "staged_bytes": staged_size,
                         "staged_sha256": hash_file(dest),
                         "kind": kind, "truncated": truncated})
    manifest = {"schema_version": 1, "source_host": socket.gethostname(),
                "source_case_dir": str(case_dir), "profile": profile,
                "max_bytes": max_bytes, "log_tail_bytes": log_tail_bytes,
                "selected": selected, "omitted": omitted,
                "selected_bytes": used,
                "full_artifacts_remain_on_worker": True}
    serialized = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    if len(serialized) > reserve:
        raise ValueError("evidence manifest exceeds reserved byte budget")
    target = stage_dir / "evidence-manifest.json"
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_bytes(serialized)
    os.replace(temporary, target)
    return {"stage_dir": str(stage_dir), "manifest": str(target),
            "transferred_bytes": used + len(serialized),
            "selected_files": len(selected), "omitted_files": len(omitted)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--profile", choices=["summary", "trace"], default="summary")
    parser.add_argument("--max-bytes", type=int, default=32 * 1024 * 1024)
    parser.add_argument("--log-tail-bytes", type=int, default=256 * 1024)
    args = parser.parse_args()
    print(json.dumps(stage(args.case_dir, args.stage_dir, args.profile,
                           args.max_bytes, args.log_tail_bytes), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
