"""Stage and run a fresh original GraphChecker scope for the timing-v2 HDFS overlay.

The command is derived from the pinned V14 planner invocation. Every changed
path and class byte is recorded; the earlier V14 scope is left intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path("/dev/shm/mallory-hdfs-balancer-v15b-node0")
PRIOR = Path("/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-short-lifetime-v1/formal-v1")
ENGINE = ROOT / "inputs/original-engine-5828ea86-catalog.jar"
OLD_OVERLAY = "/dev/shm/mallory-hdfs-balancer-short-lifetime-native-v1/adapted-test-classes"
OLD_PG0_OVERLAY = str(PRIOR / "inputs/adapted-test-classes")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--overlay-receipt", type=Path, required=True)
    args = parser.parse_args()
    assert os.uname().nodename.startswith("node0")
    assert ROOT.exists() and ENGINE.is_file()
    assert sha(ENGINE) == "9afee741b50e5e6c847e4099f917182b1fe3ff1cd29cf1ddfa9239d3a0fe4b68"
    assert args.overlay.is_dir() and args.overlay_receipt.is_file()
    assert (args.overlay / "org/apache/hadoop/hdfs/server/balancer/TestBalancerWithEncryptedTransfer.class").is_file()
    assert (args.overlay / "org/apache/hadoop/hdfs/server/blockmanagement/HeartbeatManager$Monitor.class").is_file()
    output = ROOT / "static-scope"
    original = ROOT / "original-scope"
    assert not output.exists() and not original.exists()
    base = json.loads((PRIOR / "inputs/scope-input-v1.json").read_text())
    analysis = base["analysis"]
    analysis["classpath"] = [str(args.overlay)] + [
        p for p in analysis["classpath"] if p not in (OLD_OVERLAY, OLD_PG0_OVERLAY)]
    analysis["process_dirs"] = [str(args.overlay)] + analysis["process_dirs"]
    analysis["original_engine_output_dir"] = str(original)
    base["case_id"] = "HDFS-11-BALANCER-TIMING-V2-K8-V15"
    base["adapted_workload_provenance"] = {
        "classification": "2s key interval + 2s token lifetime + 200ms NameNode monitor; same Balancer JUnit operations",
        "overlay_receipt": str(args.overlay_receipt),
        "overlay_receipt_sha256": sha(args.overlay_receipt),
        "fault_sites_override": None,
    }
    scope = ROOT / "inputs/scope-input-v15.json"
    assert not scope.exists()
    scope.write_text(json.dumps(base, indent=2, sort_keys=True) + "\n")
    prior_command = json.loads((PRIOR / "static-exit.json").read_text())["argv"]
    command = list(prior_command)
    cp = command[command.index("-cp") + 1].split(":")
    old_engine = cp[1]
    assert old_engine.endswith("bridge-engine.jar")
    cp[1] = str(ENGINE)
    command[command.index("-cp") + 1] = ":".join(cp)
    assert command[-3] == "edu.uva.liftlab.mallory.scope.ScopePlanner"
    command[-2:] = [str(scope), str(output)]
    assert all(Path(p).exists() for p in cp)
    assert subprocess.run(["pgrep", "-x", "java"], stdout=subprocess.DEVNULL).returncode != 0
    free = {name: shutil.disk_usage(path).free for name, path in {
        "root": Path("/"), "shm": Path("/dev/shm"),
        "pg0": Path("/proj/silentfailure-PG0")}.items()}
    assert free["root"] >= 2_000_000_000 and free["shm"] >= 8_000_000_000
    assert free["pg0"] >= 10_000_000_000
    receipt = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "prior_scope_input_sha256": sha(PRIOR / "inputs/scope-input-v1.json"),
               "scope_input_sha256": sha(scope), "engine_sha256": sha(ENGINE),
               "overlay_receipt_sha256": sha(args.overlay_receipt),
               "command": command, "capacity_before": free}
    pin = ROOT / "static-launch-v15.json"
    pin.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    env = dict(os.environ)
    env["TMPDIR"] = str(ROOT)
    env["XDG_CACHE_HOME"] = str(ROOT)
    started = time.monotonic()
    # PG0 contains only pinned inputs. The private mount makes accidental
    # writes impossible without changing other users' mount namespace.
    guarded = ["unshare", "-U", "-c", "--keep-caps", "-m", "--fork",
               "--propagation", "private", "sh", "-c",
               'mount --bind "$1" "$1"; mount -o remount,bind,ro "$1"; shift; exec "$@"',
               "sh", "/proj/silentfailure-PG0", *command]
    with (ROOT / "static-v15.stdout.log").open("wb") as out, (
            ROOT / "static-v15.stderr.log").open("wb") as err:
        proc = subprocess.run(guarded, cwd=ROOT, env=env, stdout=out, stderr=err,
                              timeout=1800, check=False)
    result = {"return_code": proc.returncode,
              "elapsed_seconds": round(time.monotonic() - started, 3),
              "scope_input_sha256": sha(scope), "launch_sha256": sha(pin),
              "stdout_sha256": sha(ROOT / "static-v15.stdout.log"),
              "stderr_sha256": sha(ROOT / "static-v15.stderr.log"),
              "capacity_after": {name: shutil.disk_usage(path).free for name, path in {
                  "root": Path("/"), "shm": Path("/dev/shm"),
                  "pg0": Path("/proj/silentfailure-PG0")}.items()}}
    (ROOT / "static-result-v15.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    for name in ("analysis.json", "weave_manifest.json", "static_scope_map.jsonl"):
        assert (output / name).is_file()
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
