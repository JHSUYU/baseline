#!/usr/bin/env python3
"""One fresh original DeleteReplicaTest embedded-cluster run per output path."""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path


ROOT = Path("/users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-09/actor-v2/solr16257-diff")
TEST = "org.apache.solr.cloud.DeleteReplicaTest"
METHOD = "deleteReplicaAndVerifyDirectoryCleanup"
COLLECTION_PATH = "/collections/deletereplica_test/state.json"
FAULTS = ";".join(
    [
        "HTTP_POST|/admin/cores?action=UNLOAD&core=<target>|1|caller=org.apache.solr.handler.component.HttpShardHandler#submit|actor=target_replica_http",
        "GET_CHILDREN_STAT|"
        + COLLECTION_PATH
        + "|@1|caller=org.apache.solr.common.cloud.ZkStateReader$StateWatcher#refreshAndWatchChildren|actor=target_command_reader|after=F0|seed_global=1",
        "GET_DATA|"
        + COLLECTION_PATH
        + "|@2|caller=org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState|actor=target_command_reader|after=F1|seed_global=2",
    ]
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_trace(path: Path) -> dict:
    result = {
        "fault_events": [],
        "target_events": [],
        "pre_timeout_states": [],
        "zk_actual_states": [],
        "strict_same_actor_posttarget": False,
    }
    if not path.exists():
        return result
    for raw in path.read_text(errors="replace").splitlines():
        fields = raw.split("\t")
        if len(fields) < 3:
            continue
        try:
            sequence = int(fields[0])
        except ValueError:
            continue
        kind = fields[2]
        item = {"sequence": sequence, "kind": kind, "fields": fields[3:]}
        if kind.startswith("IO_APPLIED_"):
            result["fault_events"].append(item)
        elif kind in ("TARGET_CHECK", "TARGET_EXCEPTION"):
            result["target_events"].append(item)
        elif kind == "PRE_TIMEOUT_READER_STATE":
            result["pre_timeout_states"].append(item)
        elif kind in ("ZK_ACTUAL_STATE", "ZK_ACTUAL_STATE_ERROR"):
            result["zk_actual_states"].append(item)

    faults = result["fault_events"]
    checks = [x for x in result["target_events"] if x["kind"] == "TARGET_CHECK"]
    if len(faults) == 3 and [x["sequence"] for x in faults] == sorted(x["sequence"] for x in faults):
        fault_ids = []
        client_ids = []
        for item in faults:
            joined = "\t".join(item["fields"])
            fault_ids.append(next((part for part in item["fields"] if part.startswith("fault_id=")), ""))
            client_ids.append(next((part for part in item["fields"] if part.startswith("client_id=")), ""))
            if "actor=target_command_reader" not in joined and item != faults[0]:
                client_ids[-1] = ""
        if fault_ids == ["fault_id=F0", "fault_id=F1", "fault_id=F2"] and checks:
            last_check = checks[-1]
            guard_client = next(
                (part.replace("command_client_id=", "client_id=") for part in last_check["fields"]
                 if part.startswith("command_client_id=")),
                "",
            )
            result["strict_same_actor_posttarget"] = (
                faults[-1]["sequence"] < last_check["sequence"]
                and client_ids[1] != ""
                and client_ids[1] == client_ids[2] == guard_client
                and "actor=target_replica_http" in "\t".join(faults[0]["fields"])
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", choices=["parent", "fix"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--fault", action="store_true")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scratch = output / "scratch"
    scratch.mkdir()
    source = ROOT / f"{args.version}-source"
    overlay = ROOT / f"{args.version}-overlay-classes"
    runtime_cp = (ROOT / f"{args.version}-classpath.txt").read_text().strip()
    cp = f"{overlay}:{runtime_cp}"
    if not (overlay / "baseline/solr09/FeedbackProbe.class").is_file():
        raise RuntimeError("hooked classes were not compiled")

    command = [
        "/usr/lib/jvm/java-11-openjdk-amd64/bin/java",
        "-ea", "-Xmx4g", "-Djava.awt.headless=true",
        "--add-opens=java.base/java.lang=ALL-UNNAMED",
        "--add-opens=java.base/java.util=ALL-UNNAMED",
        "-Djava.io.tmpdir=" + str(scratch),
        "-DtempDir=" + str(scratch),
        "-Dtests.seed=F0993D5343E20BA4",
        "-Dtests.src.home=" + str(source / "solr/core"),
        "-Dcommon.dir=" + str(source / "solr"),
        "-Dtests.asserts=true", "-Dtests.slow=true", "-Dtests.nightly=false",
        "-Dtests.timeoutSuite=86400000", "-Dtests.timeout=86400000",
        "-Djetty.testMode=1", "-Djetty.insecurerandom=1",
        "-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory",
        "-Djava.security.egd=file:/dev/./urandom",
        "-Dsolr09.trace=" + str(output / "events.tsv"),
        "-Dsolr09.diagnostic.read_actual=true",
        "-Dsolr09.faults=" + (FAULTS if args.fault else ""),
        "-javaagent:"
        + str(ROOT / "jacoco-agent.jar")
        + "=destfile=" + str(output / "jacoco.exec")
        + ",append=false,dumponexit=true,includes=org.apache.solr.*",
        "-cp", cp, "baseline.solr09.RunSingleJUnit", TEST, METHOD,
    ]
    start_wall = time.time()
    start_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_wall))
    log_path = output / "junit.log"
    with log_path.open("w") as log:
        try:
            process = subprocess.run(
                command, cwd=source, stdout=log, stderr=subprocess.STDOUT,
                check=False, timeout=args.timeout,
            )
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            log.write("\nSOLR09_DIFF_JUNIT_TIMEOUT\n")
    elapsed = time.time() - start_wall
    trace = output / "events.tsv"
    receipt = {
        "case_id": "SOLR-09", "differential_version": args.version,
        "test": TEST + "#" + METHOD, "faulted": args.fault,
        "fault_plan": FAULTS if args.fault else "",
        "started_utc": start_utc, "elapsed_seconds": elapsed,
        "exit_code": exit_code, "trace_review": inspect_trace(trace),
        "sha256": {path.name: sha256(path) for path in
                   (log_path, trace, output / "jacoco.exec") if path.exists()},
        "test_class_sha256": sha256(
            source / "solr/core/build/classes/java/test/org/apache/solr/cloud/DeleteReplicaTest.class"),
        "hook_class_sha256": sha256(overlay / "baseline/solr09/FeedbackProbe.class"),
        "command": command,
    }
    temporary = output / "receipt.json.tmp"
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    temporary.replace(output / "receipt.json")
    print(json.dumps({key: receipt[key] for key in
                      ("differential_version", "faulted", "elapsed_seconds", "exit_code")}), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
