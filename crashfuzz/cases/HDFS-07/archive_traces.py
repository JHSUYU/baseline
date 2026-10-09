"""Pack completed HDFS-07 GraphChecker traces without removing source evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "HDFS-07-traces.tar.gz"
MANIFEST = HERE / "trace-archive-manifest.json"
NAMES = (
    "healthy", "healthy-ipc", "healthy-ipc-door", "healthy-control-door",
    *(f"trial-{number:02d}" for number in range(1, 6)),
    *(f"control-rpc-{number:02d}" for number in range(1, 16)),
    "followup-eof", "followup-timeout", "followup-paxos", "followup-mutation",
    "alt-testNewerVersionOfSegmentWins", "alt-testNewerVersionOfSegmentWins2",
    "alt-testInProgressRecovery", "alt-testCrashAtBeginningOfSegment",
)


def main() -> None:
    if ARCHIVE.exists() and MANIFEST.exists():
        print(MANIFEST.read_text())
        return
    included = []
    with tarfile.open(ARCHIVE, "w:gz", compresslevel=6) as archive:
        for name in NAMES:
            trace = HERE / name / "trace"
            if trace.is_dir():
                archive.add(trace, arcname=name + "/trace")
                included.append(name)
    digest = hashlib.sha256()
    with ARCHIVE.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    data = {"archive": ARCHIVE.name, "sha256": digest.hexdigest(),
            "size_bytes": ARCHIVE.stat().st_size, "trace_directories": included}
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
