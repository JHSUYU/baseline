#!/usr/bin/env python3
"""CAS-commit only reviewed HBASE-32 progress into the shared checklist."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

CASE = Path(__file__).resolve().parent.parent
PIVOT = CASE.parent.parent
RESULT = CASE / "result.json"
CHECKLIST = PIVOT / "checklist102.json"
MARKDOWN = PIVOT / "checklist102.md"


def git(*args, env=None):
    return subprocess.check_output(["git", *map(str, args)], env=env, text=True).strip()


def main():
    repo = Path(git("rev-parse", "--show-toplevel"))
    evidence = [Path(path).resolve() for path in sys.argv[1:]]
    for path in evidence:
        if not path.is_file() or not path.is_relative_to(CASE):
            raise ValueError("Only existing case-local evidence may be committed: " + str(path))
    result = json.loads(RESULT.read_text())
    spec = importlib.util.spec_from_file_location("checklist", PIVOT / "checklist.py")
    checklist = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checklist)
    files = [RESULT, CHECKLIST, MARKDOWN, Path(__file__), *evidence]
    for attempt in range(8):
        previous = git("rev-parse", "HEAD")
        data = json.loads(git("show", previous + ":" + str(CHECKLIST.relative_to(repo))))
        row = next(item for item in data["rows"] if item["case_id"] == "HBASE-32")
        if row["status"] != result["status"]:
            raise RuntimeError("HBASE-32 status changed in HEAD")
        row["bug_mark"] = result["bug_mark"]
        row["supplemental_stage"] = result["supplemental_stage"]
        row["evidence"] = list(dict.fromkeys(
            row.get("evidence", []) + [str(path.relative_to(CASE)) for path in evidence]))
        CHECKLIST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        MARKDOWN.write_text(checklist.markdown(data["rows"]))
        descriptor, index = tempfile.mkstemp(prefix="hbase32-private-index-")
        os.close(descriptor)
        Path(index).unlink()
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = index
        try:
            git("read-tree", previous, env=env)
            git("add", "-f", "--", *(path.relative_to(repo) for path in files),
                env=env)
            tree = git("write-tree", env=env)
            commit = git("commit-tree", tree, "-p", previous, "-m",
                         "Update HBASE-32 supplemental progress", env=env)
            update = subprocess.run(
                ["git", "update-ref", "refs/heads/main", commit, previous],
                text=True, capture_output=True)
            if update.returncode == 0:
                if git("rev-parse", "HEAD") != commit:
                    raise RuntimeError("HEAD moved after CAS commit")
                paths = set(git("ls-tree", "-r", "--name-only", commit).splitlines())
                if not all(str(path.relative_to(repo)) in paths for path in files):
                    raise RuntimeError("Committed tree lacks case evidence")
                print(commit)
                return
            if attempt == 7:
                raise RuntimeError(update.stderr)
        finally:
            Path(index).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
