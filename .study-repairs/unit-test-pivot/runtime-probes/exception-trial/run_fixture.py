#!/usr/bin/env python3
"""Replay exception-selector behavior with an existing instrumented runtime JAR."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNS = None
CLASSPATH = None
JAVA = None
TEST = "edu.uva.liftlab.graphchecker.runtime.FaultTrialWorkload"
METHOD = "testDoorAndTarget"
TARGET = f"<{TEST}: void {METHOD}()>#u22"


def events(directory):
    return [json.loads(line) for line in
            (directory / "runtime_trace.jsonl").read_text().splitlines()]


def run(name, trial=None):
    directory = RUNS / name
    directory.mkdir(parents=True)
    cmd = [str(JAVA), f"-Dcausynth.trace.test={TEST}#{METHOD}"]
    if trial is not None:
        spec = RUNS / (name + ".json")
        spec.write_text(json.dumps(trial) + "\n")
        cmd.append(f"-Dcausynth.fault.trial={spec}")
    cmd += ["-cp", CLASSPATH,
            "edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner",
            TEST, METHOD]
    env = os.environ.copy()
    env["CAUSYNTH_TRACE_OUTPUT_DIR"] = str(directory)
    completed = subprocess.run(cmd, cwd=HERE, env=env,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    (directory / "stdout.txt").write_text(completed.stdout)
    (directory / "stderr.txt").write_text(completed.stderr)
    assert completed.returncode == 0, (name, completed.stderr)
    manifest = json.loads((directory / "streaming_trace_manifest.json").read_text())
    assert manifest["status"] == "CLOSED", (name, manifest)
    return events(directory)


def chosen(rows, kind):
    return [row for row in rows if row.get("event") == kind]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path,
                        help="Existing runtime JAR with exception-trial controller")
    parser.add_argument("--out", required=True, type=Path,
                        help="Scratch output directory outside this source artifact")
    parser.add_argument("--java", type=Path,
                        default=Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/java"))
    parser.add_argument("--javac", type=Path,
                        default=Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/javac"))
    args = parser.parse_args()
    assert args.jar.is_file(), args.jar
    output = args.out.resolve()
    assert output != HERE and HERE not in output.parents, output
    output.mkdir(parents=True, exist_ok=True)
    classes = output / "classes"
    classes.mkdir(exist_ok=True)
    home = Path.home()
    junit = home / ".m2/repository/junit/junit/4.13.2/junit-4.13.2.jar"
    hamcrest = home / ".m2/repository/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar"
    global RUNS, CLASSPATH, JAVA
    RUNS = output / "runs"
    CLASSPATH = os.pathsep.join(map(str, (classes, args.jar, junit, hamcrest)))
    JAVA = args.java
    subprocess.run([str(args.javac), "-cp", CLASSPATH, "-d", str(classes),
                    str(HERE / "fixtures/FaultTrialWorkload.java"),
                    str(HERE / "fixtures/TraceParseSmoke.java")], check=True)
    if RUNS.exists():
        shutil.rmtree(RUNS)
    RUNS.mkdir()

    healthy = run("healthy")
    observed = chosen(healthy, "FAULT_POINT_OBSERVED")
    assert [row["hitOrdinal"] for row in observed] == [1, 2, 1, 2], observed
    assert observed[0]["occurrenceAddress"] != observed[2]["occurrenceAddress"]
    assert (observed[0]["occurrenceAddress"].split("/region/")[1]
            .split("/ctx:")[0] ==
            observed[2]["occurrenceAddress"].split("/region/")[1]
            .split("/ctx:")[0] == "REGION.fixture")
    assert not chosen(healthy, "FAULT_APPLIED")
    assert chosen(healthy, "BRANCH")[-1]["siteId"] == TARGET

    faults = [{key: point[key] for key in
               ("marker", "siteId", "sourceKey", "hitOrdinal")}
              for point in observed[:2]]
    for index, fault in enumerate(faults, 1):
        fault.update(faultId=f"fixture-{index}",
                     occurrence=observed[index - 1]["occurrenceAddress"],
                     value=True)

    one = run("one_fault", {"schemaVersion": 1, "faults": faults[:1],
                            "targetSiteId": TARGET,
                            "targetRegionId": "REGION.fixture"})
    assert len(chosen(one, "FAULT_APPLIED")) == 1
    assert chosen(one, "FAULT_TRIAL_SUMMARY")[0]["applied"] == 1
    assert chosen(one, "FAULT_TRIAL_SUMMARY")[0]["targetAfterFault"]

    two = run("two_faults", {"schemaVersion": 1, "faults": faults,
                             "targetSiteId": TARGET,
                             "targetRegionId": "REGION.fixture"})
    applied = chosen(two, "FAULT_APPLIED")
    assert [row["faultId"] for row in applied] == ["fixture-1", "fixture-2"]
    branch = chosen(two, "BRANCH")[-1]
    assert branch["seq"] > applied[-1]["seq"] and branch["siteId"] == TARGET
    summary = chosen(two, "FAULT_TRIAL_SUMMARY")[0]
    assert (summary["requested"], summary["matched"], summary["applied"]) == (2, 2, 2)
    assert summary["targetAfterFault"]

    second_context = dict(faults[0], faultId="fixture-second-context",
                          occurrence=observed[2]["occurrenceAddress"],
                          hitOrdinal=1)
    different = run("second_context", {"schemaVersion": 1,
                                       "faults": [second_context],
                                       "targetSiteId": TARGET})
    assert [(row["faultId"], row["hitOrdinal"])
            for row in chosen(different, "FAULT_APPLIED")] == [
                ("fixture-second-context", 1)]
    assert chosen(different, "FAULT_APPLIED")[0]["seq"] > [
        row["seq"] for row in chosen(different, "FAULT_POINT_OBSERVED")][1]

    same_id_other_address = dict(faults[0], faultId="fixture-alias",
                                 occurrence=faults[0]["occurrence"].replace(
                                     "node1#epoch0", "node1#epoch00", 1))
    alias = run("same_id_other_address", {"schemaVersion": 1,
                                         "faults": [same_id_other_address],
                                         "targetSiteId": TARGET})
    assert not chosen(alias, "FAULT_APPLIED")
    alias_summary = chosen(alias, "FAULT_TRIAL_SUMMARY")[0]
    assert alias_summary["matched"] == 0
    assert alias_summary["occurrenceId"] == observed[0]["occurrenceId"]
    assert alias_summary["occurrenceAddress"] != observed[0]["occurrenceAddress"]

    subprocess.run([str(JAVA), "-cp", CLASSPATH,
                    "edu.uva.liftlab.graphchecker.runtime.TraceParseSmoke",
                    str(RUNS / "two_faults")], cwd=HERE, check=True)

    missed_fault = dict(faults[0], siteId="<missing: void noSuchSite()>#u1")
    missed = run("unmatched", {"schemaVersion": 1, "faults": [missed_fault],
                               "targetSiteId": TARGET})
    assert not chosen(missed, "FAULT_APPLIED")
    summary = chosen(missed, "FAULT_TRIAL_SUMMARY")[0]
    assert (summary["requested"], summary["matched"], summary["applied"]) == (1, 0, 0)
    assert summary["targetAfterFault"] is False
    print("PASS same JUnit method: healthy, one fault, ordered two faults,"
          " distinct context, same-ID address alias rejected, unmatched")


if __name__ == "__main__":
    main()
