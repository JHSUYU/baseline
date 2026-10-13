"""Host-local native GraphChecker checklist and one-case resume command."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from .checklist import (DEFAULT_INVENTORY, DEFAULT_OWNERSHIP,
                        _sha, build_checklist, build_distributed_checklist,
                        run_next, tsv)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "run-next"))
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--ownership", type=Path, default=DEFAULT_OWNERSHIP)
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--host", choices=("node0", "node1", "node2"))
    parser.add_argument("--format", choices=("json", "tsv"), default="json")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--remote", action="store_true",
                        help="on node0, collect audited owner rows from node1/node2")
    parser.add_argument("--ssh-key", type=Path)
    args = parser.parse_args()
    if args.command == "run-next":
        if args.remote:
            parser.error("--remote is status-only")
        if not args.host:
            parser.error("run-next requires --host")
        result = run_next(args.inventory, args.ownership, args.config_root,
                          args.state_root, args.host, args.reviews)
        print(json.dumps(result, sort_keys=True))
        return
    if args.remote and args.host:
        parser.error("--remote cannot be combined with --host")
    rows = (build_distributed_checklist(args.inventory, args.ownership,
                                       args.config_root, args.state_root,
                                       args.reviews, args.ssh_key)
            if args.remote else
            build_checklist(args.inventory, args.ownership, args.config_root,
                            args.state_root, args.reviews, args.host))
    output = tsv(rows) if args.format == "tsv" else json.dumps(
        {"schema_version": 1, "inventory_total": 102,
         "inventory_sha256": _sha(args.inventory),
         "ownership_sha256": _sha(args.ownership),
         "dispatcher_source_sha256": _sha(Path(__file__).with_name("checklist.py")),
         "selected_rows": len(rows),
         "native_tested_complete": sum(row["native_tested_complete"] for row in rows),
         "rows": rows}, sort_keys=True, indent=2) + "\n"
    if args.out is None:
        print(output, end="")
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".native-checklist-",
                                             dir=args.out.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, args.out)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    main()
