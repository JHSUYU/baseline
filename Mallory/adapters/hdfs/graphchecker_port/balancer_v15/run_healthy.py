"""One unchanged Balancer JUnit under the pinned timing-only V15 overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

ROOT = Path("/dev/shm/mallory-hdfs-balancer-v15b-node0")
PRIOR_CONFIG = ROOT / "inputs/prior-campaign-config-v14.json"
OVERLAY = Path("/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-monitor-v3-combined/overlay")
ENGINE = ROOT / "inputs/original-engine-5828ea86-catalog.jar"
ADAPTER = ROOT / "inputs/native-adapter-5828ea86.jar"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def capacity() -> dict[str, int]:
    return {name: shutil.disk_usage(path).free for name, path in {
        "root": Path("/"), "shm": Path("/dev/shm"),
        "pg0": Path("/proj/silentfailure-PG0")}.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", choices=("healthy1", "healthy2"), required=True)
    args = parser.parse_args()
    assert os.uname().nodename.startswith("node0")
    static = json.loads((ROOT / "static-result-v15.json").read_text())
    weave = json.loads((ROOT / "weave-result-v15.json").read_text())
    assert static["return_code"] == weave["return_code"] == 0
    assert sha(ENGINE) == "9afee741b50e5e6c847e4099f917182b1fe3ff1cd29cf1ddfa9239d3a0fe4b68"
    assert sha(ADAPTER) == "856de4cd245da328ba33486c2b6e2f943486ac93676a71d49de4585571971aa0"
    scope = ROOT / "original-scope/static_scope_map.jsonl"
    woven = ROOT / "woven"
    assert scope.is_file() and (woven / "native-original-weave-receipt.json").is_file()
    # A separate experiment may use Java on this host. Refuse only another
    # instance of this exact JUnit workload, which would collide on its ports.
    test_class = b"org.apache.hadoop.hdfs.server.balancer.TestBalancerWithEncryptedTransfer"
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal() or int(proc.name) == os.getpid():
            continue
        try:
            args = (proc / "cmdline").read_bytes().split(b"\0")
        except (OSError, PermissionError):
            continue
        assert not (test_class in args and b"testEncryptedBalancer0" in args), (
            "another Balancer JUnit is active", proc.name)
    before = capacity()
    assert before["root"] >= 2_000_000_000 and before["shm"] >= 8_000_000_000
    assert before["pg0"] >= 10_000_000_000
    run = ROOT / args.seed
    work = ROOT / (args.seed + "-work")
    assert not run.exists() and not work.exists()
    run.mkdir()
    work.mkdir()
    (run / "trace").mkdir()
    (run / "fault-plan.json").write_text('{"faults": []}\n')
    prior = json.loads(PRIOR_CONFIG.read_text())
    assert sha(PRIOR_CONFIG) == "ac318753d1eba1b0e54981f5380c5a32849d0a0a598ff1d76367e1cc9883d260"
    assert prior["junit"] == {"class":
        "org.apache.hadoop.hdfs.server.balancer.TestBalancerWithEncryptedTransfer",
        "method": "testEncryptedBalancer0"}
    old = prior["runner"]["classpath"]
    cp = [str(woven), str(OVERLAY), str(ENGINE), str(ADAPTER)] + [p for p in old
        if p not in old[:4] and "native-fault-adapter" not in p]
    assert all(Path(p).exists() for p in cp)
    test = prior["junit"]
    selector = test["class"] + "#" + test["method"]
    argv = [prior["runner"]["zero_vm_java"],
            "-Dcausynth.trace.mode=region-state",
            "-Dcausynth.trace.test=" + selector,
            "-Dmallory.gc.nativeFaultDoorContext=true",
            "-Xmx4g", "-ea", "-Djava.io.tmpdir=" + str(work),
            "-Dtest.build.data=" + str(work),
            "-Dhadoop.log.dir=" + str(work),
            "-cp", os.pathsep.join(cp), prior["runner"]["main_class"],
            test["class"], test["method"]]
    env = dict(os.environ)
    env.update({"CAUSYNTH_STATIC_SCOPE_MAP": str(scope),
                "CAUSYNTH_TRACE_OUTPUT_DIR": str(run / "trace"),
                "MALLORY_NATIVE_FAULT_PLAN": str(run / "fault-plan.json"),
                "MALLORY_NATIVE_FAULT_EVENTS": str(run / "fault-events.jsonl"),
                "TMPDIR": str(work), "XDG_CACHE_HOME": str(work)})
    env.pop("CAUSYNTH_CONCOLIC_SESSIONS", None)
    launch = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "argv": argv, "static_map_sha256": sha(scope),
              "weave_receipt_sha256": sha(woven / "native-original-weave-receipt.json"),
              "overlay_pin_sha256": sha(ROOT / "inputs/combined-overlay-pin-v15.json"),
              "capacity_before": before}
    (run / "launch.json").write_text(json.dumps(launch, indent=2, sort_keys=True) + "\n")
    guarded = ["unshare", "-U", "-c", "--keep-caps", "-m", "--fork",
               "--propagation", "private", "sh", "-c",
               'mount --bind "$1" "$1"; mount -o remount,bind,ro "$1"; shift; exec "$@"',
               "sh", "/proj/silentfailure-PG0", *argv]
    started = time.monotonic()
    stop_reason = None
    with (run / "stdout.log").open("wb") as out, (
            run / "stderr.log").open("wb") as err:
        process = subprocess.Popen(guarded, cwd=work, env=env, stdout=out,
                                   stderr=err, start_new_session=True)
        (run / "process.json").write_text(json.dumps({"pid": process.pid,
            "started_utc": launch["created_utc"]}, indent=2) + "\n")
        while process.poll() is None:
            time.sleep(1)
            now = capacity()
            if now["root"] < 1_600_000_000 or now["shm"] < 5_000_000_000 or (
                    now["pg0"] < 10_000_000_000):
                stop_reason = "capacity_floor"
            elif time.monotonic() - started > 600:
                stop_reason = "junit_timeout"
            if stop_reason:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                break
    result = {"return_code": process.wait(), "stop_reason": stop_reason,
              "elapsed_seconds": round(time.monotonic() - started, 3),
              "capacity_after": capacity(), "stdout_sha256": sha(run / "stdout.log"),
              "stderr_sha256": sha(run / "stderr.log")}
    (run / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True), flush=True)
    if result["return_code"] != 0 or stop_reason:
        raise SystemExit(1)
    assert (run / "trace/streaming_trace_manifest.json").is_file()


if __name__ == "__main__":
    main()
