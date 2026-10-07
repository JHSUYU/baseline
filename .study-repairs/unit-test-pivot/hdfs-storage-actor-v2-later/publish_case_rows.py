#!/usr/bin/env python3
"""CAS-publish selected completed cases into the shared 104-row checklist.

Rebuilds the checklist from the current HEAD table plus only the named case
rows. This avoids publishing another agent's uncommitted worktree rows.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
import checklist  # noqa: E402

TABLE_JSON = ".study-repairs/unit-test-pivot/checklist102.json"
TABLE_MD = ".study-repairs/unit-test-pivot/checklist102.md"
TERMINAL = {"quality_complete", "confirmed_bug", "no_cluster_test",
            "no_usable_cluster_test", "source_excluded"}


def git(*args: str, input_bytes: bytes | None = None,
        env: dict[str, str] | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, env=env, input=input_bytes,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True).stdout


def candidate(old: str, cases: list[str], index_path: str) -> tuple[str, dict, list[str]]:
    base = json.loads(git("show", f"{old}:{TABLE_JSON}"))
    fresh = {row["case_id"]: row for row in checklist.rows()}
    wanted = set(cases)
    if len(wanted) != len(cases):
        raise RuntimeError("duplicate case ID")
    if not wanted.issubset(fresh):
        raise RuntimeError("case missing from rendered selection")
    for case in wanted:
        if fresh[case]["status"] not in TERMINAL:
            raise RuntimeError(f"{case} is not terminal")
        if fresh[case]["status"] == "quality_complete" and (
                fresh[case].get("fault_trials", 0) <= 0 or
                fresh[case].get("target_after_fault", 0) <= 0):
            raise RuntimeError(f"{case} lacks completed fault evidence")
    touched: list[str] = []
    for index, row in enumerate(base["rows"]):
        if row["case_id"] in wanted:
            base["rows"][index] = fresh[row["case_id"]]
            touched.append(row["case_id"])
    if set(touched) != wanted or len(base["rows"]) != 104:
        raise RuntimeError("HEAD checklist case set/count changed")
    data = {
        TABLE_JSON: (json.dumps(base, sort_keys=True, indent=2) + "\n").encode(),
        TABLE_MD: checklist.markdown(base["rows"]).encode(),
    }
    env = {**os.environ, "GIT_INDEX_FILE": index_path}
    git("read-tree", old, env=env)
    paths = [f".study-repairs/unit-test-pivot/cases/{case}/result.json"
             for case in cases]
    git("add", "-f", "--", *paths, env=env)
    for path, blob in data.items():
        oid = git("hash-object", "-w", "--stdin", input_bytes=blob).decode().strip()
        git("update-index", "--add", "--cacheinfo", f"100644,{oid},{path}", env=env)
    tree = git("write-tree", env=env).decode().strip()
    return tree, base, touched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_ids", nargs="+")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    for attempt in range(8):
        old = git("rev-parse", "HEAD").decode().strip()
        with tempfile.TemporaryDirectory() as tmp:
            tree, base, touched = candidate(old, args.case_ids, tmp + "/index")
        if not args.publish:
            print(json.dumps({"dry_run": True, "head": old, "tree": tree,
                              "cases": touched, "rows": len(base["rows"])},
                             sort_keys=True))
            return
        message = "Publish actor-V2 storage case rows: " + ", ".join(touched)
        new = git("commit-tree", tree, "-p", old,
                  input_bytes=(message + "\n").encode()).decode().strip()
        result = subprocess.run(["git", "update-ref", "refs/heads/main", new, old],
                                cwd=ROOT, capture_output=True, text=True)
        if result.returncode == 0:
            print(json.dumps({"commit": new, "previous": old,
                              "cases": touched, "rows": len(base["rows"])},
                             sort_keys=True))
            return
    raise RuntimeError("HEAD changed during all eight CAS attempts")


if __name__ == "__main__":
    main()
