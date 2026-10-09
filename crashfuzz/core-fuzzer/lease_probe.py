#!/usr/bin/env python3
"""Probe whether a shared filesystem honors the campaign's cross-host lock."""

import argparse
import json
import socket
import time
from pathlib import Path

from fuzzer import CaseLease, atomic_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("hold", "try"))
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("--seconds", type=int, default=8)
    args = parser.parse_args()
    if args.action == "hold":
        with CaseLease(args.case_dir):
            atomic_json(args.case_dir / "probe-ready.json",
                        {"host": socket.gethostname(), "ready": time.time()})
            time.sleep(args.seconds)
        print(json.dumps({"result": "released", "host": socket.gethostname()}))
    else:
        try:
            with CaseLease(args.case_dir):
                print(json.dumps({"result": "ACQUIRED_WHILE_HELD",
                                  "host": socket.gethostname()}))
                raise SystemExit(2)
        except RuntimeError as error:
            if "already claimed" not in str(error) and "lease still live" not in str(error):
                raise
            print(json.dumps({"result": "blocked", "host": socket.gethostname()}))


if __name__ == "__main__":
    main()
