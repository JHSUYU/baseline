#!/usr/bin/env python3
"""Three fresh exact-build replays of the SOLR-40 alias-read-only candidate."""

from pathlib import Path
import json
import shutil

import alias_read_only_control as control


if __name__ == "__main__":
    original = control.OUT
    control.OUT = control.CASE / "evidence/alias-read-only-v12b-replay"
    control.OUT.mkdir(parents=True, exist_ok=True)
    source = original / "build-receipt.json"
    destination = control.OUT / "build-receipt.json"
    if not destination.exists():
        shutil.copy2(source, destination)
    elif destination.read_bytes() != source.read_bytes():
        raise RuntimeError("Exact replay build receipt changed")
    summary = control.OUT / "summary.json"
    completed = len(json.loads(summary.read_text())["runs"]) if summary.exists() else 0
    if completed > 3:
        raise RuntimeError("Exact replay exceeded the three-run bound")
    if completed < 3:
        control.main(3 - completed)
