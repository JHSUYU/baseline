"""Weave one byte-pinned V15 HDFS overlay after successful static analysis."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path("/dev/shm/mallory-hdfs-balancer-v15b-node0")
CONFIG = ROOT / "inputs/native-weave-config-v15b.json"
ENGINE = Path(__file__).resolve().parents[4] / "static_scope_port/original_engine"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    assert os.uname().nodename.startswith("node0")
    static = json.loads((ROOT / "static-result-v15.json").read_text())
    assert static["return_code"] == 0
    assert sha(CONFIG) == "fea71b0f9fbfd4359805265b7d60c1f26ac1793845c6e0dbd0835d5a82d3900f"
    assert sha(ENGINE / "target/mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar") == (
        "9afee741b50e5e6c847e4099f917182b1fe3ff1cd29cf1ddfa9239d3a0fe4b68")
    assert (ENGINE / "target/native-original-engine-receipt.json").is_file()
    config = json.loads(CONFIG.read_text())
    assert Path(config["native_fault_manifest"]).is_file()
    assert Path(config["region_skeletons"]).is_file()
    assert not Path(config["output_classes"]).exists()
    assert subprocess.run(["pgrep", "-x", "java"], stdout=subprocess.DEVNULL).returncode != 0
    free = {name: shutil.disk_usage(path).free for name, path in {
        "root": Path("/"), "shm": Path("/dev/shm"),
        "pg0": Path("/proj/silentfailure-PG0")}.items()}
    assert free["root"] >= 2_000_000_000 and free["shm"] >= 8_000_000_000
    assert free["pg0"] >= 10_000_000_000
    env = dict(os.environ)
    env["MALLORY_NATIVE_ENGINE_ROOT"] = str(ENGINE)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[5])
    env["TMPDIR"] = str(ROOT)
    env["XDG_CACHE_HOME"] = str(ROOT)
    command = ["python3", "-m", "Mallory.instrumentation.graphchecker_port.native_original_weave",
               "--config", str(CONFIG)]
    (ROOT / "weave-launch-v15.json").write_text(json.dumps({
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "command": command, "config_sha256": sha(CONFIG),
        "engine_receipt_sha256": sha(ENGINE / "target/native-original-engine-receipt.json"),
        "capacity_before": free}, indent=2, sort_keys=True) + "\n")
    guarded = ["unshare", "-U", "-c", "--keep-caps", "-m", "--fork",
               "--propagation", "private", "sh", "-c",
               'mount --bind "$1" "$1"; mount -o remount,bind,ro "$1"; shift; exec "$@"',
               "sh", "/proj/silentfailure-PG0", *command]
    started = time.monotonic()
    with (ROOT / "weave-v15.stdout.log").open("wb") as out, (
            ROOT / "weave-v15.stderr.log").open("wb") as err:
        done = subprocess.run(guarded, cwd=ROOT, env=env, stdout=out, stderr=err,
                              timeout=900, check=False)
    result = {"return_code": done.returncode,
              "elapsed_seconds": round(time.monotonic() - started, 3),
              "stdout_sha256": sha(ROOT / "weave-v15.stdout.log"),
              "stderr_sha256": sha(ROOT / "weave-v15.stderr.log"),
              "capacity_after": {name: shutil.disk_usage(path).free for name, path in {
                  "root": Path("/"), "shm": Path("/dev/shm"),
                  "pg0": Path("/proj/silentfailure-PG0")}.items()}}
    if done.returncode == 0:
        result["weave_receipt_sha256"] = sha(
            Path(config["output_classes"]) / "native-original-weave-receipt.json")
    (ROOT / "weave-result-v15.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True), flush=True)
    if done.returncode != 0:
        raise SystemExit(done.returncode)


if __name__ == "__main__":
    main()
