#!/usr/bin/env python3
"""Run one isolated HDFS-55 DN wire control and checkpoint its exit status."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CASE = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--mode", choices=("original", "fixed"), required=True)
    parser.add_argument("--variant", choices=("timeout-only", "serial", "one-node"),
                        default="one-node")
    parser.add_argument("--policy", choices=("healthy", "persistent", "finite"),
                        required=True)
    parser.add_argument("--rejections", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    if args.policy == "finite" and args.rejections <= 0:
        parser.error("finite policy needs a positive rejection count")
    if args.policy != "finite" and args.rejections:
        parser.error("rejections only apply to finite policy")
    output = HERE / "runs" / args.name
    if output.exists():
        parser.error("run directory already exists: " + str(output))
    output.mkdir(parents=True)
    overlay = HERE / "build-nonce" / (args.mode + "-overlay")
    fixture = HERE / "build" / (args.variant + "-test-overlay")
    cmd = [sys.executable, str(CASE / "run_control.py"), "--output", str(output),
           "--overlay", str(overlay), "--test-overlay", str(fixture),
           "--timeout", str(args.timeout)]
    if args.policy == "persistent":
        cmd.extend(("--inject", "--dn-reject-persistent"))
    elif args.policy == "finite":
        cmd.extend(("--inject", "--dn-reject-cached-key", str(args.rejections)))
    with (output / "driver.log").open("w") as stream:
        completed = subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT)
    summary = {"name": args.name, "policy": args.policy, "mode": args.mode,
               "variant": args.variant, "requested_rejections": args.rejections,
               "logical_faults_planned": 1 if args.policy == "persistent" else None,
               "returncode": completed.returncode,
               "manifest": str(output / "manifest.json")}
    tmp = output / "launcher.json.tmp"
    tmp.write_text(json.dumps(summary, indent=2) + "\n")
    tmp.replace(output / "launcher.json")
    print(json.dumps(summary), flush=True)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
