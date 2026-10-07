#!/usr/bin/env python3
"""One unchanged Solr 8.11.4 DeleteReplicaTest run with a distinct class overlay."""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "same8114-causal/source"
TEST = "org.apache.solr.cloud.DeleteReplicaTest"
METHOD = "deleteReplicaAndVerifyDirectoryCleanup"
ZK_PATH = "/collections/deletereplica_test/state.json"
FAULTS = ";".join([
    "HTTP_POST|/admin/cores?action=UNLOAD&core=<target>|1|"
    "caller=org.apache.solr.handler.component.ShardRequestor#call:130|"
    "actor=target_replica_http",
    "GET_CHILDREN_STAT|" + ZK_PATH + "|@1|"
    "caller=org.apache.solr.common.cloud.ZkStateReader$StateWatcher#"
    "refreshAndWatchChildren:1405|actor=target_overseer|after=F0|seed_global=1",
    "GET_DATA|" + ZK_PATH + "|@2|"
    "caller=org.apache.solr.common.cloud.ZkStateReader#"
    "fetchCollectionState:1641|actor=target_overseer|after=F1|seed_global=2",
])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_trace(path: Path) -> dict:
    result = {"applied": [], "target_checks": [], "target_exceptions": [],
              "pre_timeout_states": [], "zk_actual_states": [],
              "causal_refreshes": [], "strict_same_actor_posttarget": False}
    if not path.exists():
        return result
    for raw in path.read_text(errors="replace").splitlines():
        fields = raw.split("\t")
        if len(fields) < 4:
            continue
        try:
            sequence = int(fields[0])
        except ValueError:
            continue
        kind = fields[2]
        item = {"sequence": sequence, "kind": kind, "fields": fields[3:]}
        if kind.startswith("IO_APPLIED_"):
            result["applied"].append(item)
        elif kind == "TARGET_CHECK":
            result["target_checks"].append(item)
        elif kind == "TARGET_EXCEPTION":
            result["target_exceptions"].append(item)
        elif kind == "PRE_TIMEOUT_READER_STATE":
            result["pre_timeout_states"].append(item)
        elif kind.startswith("ZK_ACTUAL_STATE"):
            result["zk_actual_states"].append(item)
        elif kind == "CAUSAL_REFRESH":
            result["causal_refreshes"].append(item)
    applied = result["applied"]
    checks = result["target_checks"]
    if len(applied) == 3 and checks:
        ids = [next((field for field in item["fields"] if field.startswith("fault_id=")), "")
               for item in applied]
        clients = [next((field for field in item["fields"] if field.startswith("client_id=")), "")
                   for item in applied]
        overseer = next((field.replace("overseer_client_id=", "client_id=")
                         for field in checks[-1]["fields"]
                         if field.startswith("overseer_client_id=")), "")
        result["strict_same_actor_posttarget"] = (
            ids == ["fault_id=F0", "fault_id=F1", "fault_id=F2"]
            and applied[0]["sequence"] < applied[1]["sequence"]
            < applied[2]["sequence"] < checks[-1]["sequence"]
            and "actor=target_replica_http" in applied[0]["fields"]
            and "actor=target_overseer" in applied[1]["fields"]
            and "actor=target_overseer" in applied[2]["fields"]
            and clients[1] != "" and clients[1] == clients[2] == overseer
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["baseline", "causal"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--fault", action="store_true")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    scratch = output / "scratch"
    scratch.mkdir()
    overlay = ROOT / ("same8114-causal/" + args.mode + "-classes")
    cp = (ROOT / "same8114-causal" / (args.mode + "-classpath.txt")).read_text().strip()
    command = [
        "/usr/lib/jvm/java-8-openjdk-amd64/bin/java", "-ea", "-Xmx3g",
        "-Djava.awt.headless=true",
        "-Djava.io.tmpdir=" + str(scratch), "-DtempDir=" + str(scratch),
        "-Dtests.seed=F0993D5343E20BA4",
        "-Dtests.src.home=" + str(SOURCE / "solr/core"),
        "-Dcommon.dir=" + str(SOURCE / "lucene"),
        "-Dtests.asserts=true", "-Dtests.slow=true", "-Dtests.nightly=false",
        "-Dtests.timeoutSuite=86400000", "-Dtests.timeout=86400000",
        "-Djetty.testMode=1", "-Djetty.insecurerandom=1",
        "-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory",
        "-Djdk.map.althashing.threshold=0",
        "-Djava.security.egd=file:/dev/./urandom",
        "-Dsolr09.trace=" + str(output / "events.tsv"),
        "-Dsolr09.diagnostic.read_actual=true",
        "-Dsolr09.faults=" + (FAULTS if args.fault else ""),
        "-javaagent:" + str(ROOT / "jacoco-agent.jar")
        + "=destfile=" + str(output / "jacoco.exec")
        + ",append=false,dumponexit=true,includes=org.apache.solr.*",
        "-cp", cp, "baseline.solr09.RunSingleJUnit", TEST, METHOD,
    ]
    start = time.time()
    with (output / "junit.log").open("w") as log:
        try:
            completed = subprocess.run(command, cwd=SOURCE, stdout=log,
                                       stderr=subprocess.STDOUT, timeout=args.timeout,
                                       check=False)
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            log.write("\nSOLR09_SAME_VERSION_TIMEOUT\n")
            exit_code = 124
    receipt = {
        "case_id": "SOLR-09", "mode": args.mode,
        "classification": "experimental_causal_fix" if args.mode == "causal" else "unmodified_logic_control",
        "test": TEST + "#" + METHOD, "faulted": args.fault,
        "fault_plan": FAULTS if args.fault else "",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)),
        "elapsed_seconds": time.time() - start, "exit_code": exit_code,
        "trace_review": inspect_trace(output / "events.tsv"),
        "sha256": {path.name: sha256(path) for path in
                   (output / "junit.log", output / "events.tsv", output / "jacoco.exec")
                   if path.exists()},
        "test_class_sha256": sha256(overlay / "org/apache/solr/cloud/DeleteReplicaTest.class"),
        "command": command,
    }
    temporary = output / "receipt.json.tmp"
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    temporary.replace(output / "receipt.json")
    print(json.dumps({key: receipt[key] for key in
                      ("mode", "faulted", "elapsed_seconds", "exit_code")}), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
