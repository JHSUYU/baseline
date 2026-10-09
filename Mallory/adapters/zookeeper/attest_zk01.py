#!/usr/bin/env python3
"""Independently attest the pinned ZOOKEEPER-01 campaign after termination."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile


TARGET_CLASS = "org.apache.zookeeper.server.SessionTrackerImpl"
CHECK = TARGET_CLASS + "#checkSession(JLjava/lang/Object;)V@319:branch:2"
THROW = TARGET_CLASS + "#checkSession(JLjava/lang/Object;)V@320:throw:1"
SOURCE = "zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java"
CLASS_ARCHIVE = "posthoc/SessionTrackerImpl.ca545363df047e5c.class"
SOURCE_ARCHIVE = "posthoc/executed-source.tar.gz"
AGENT_ARCHIVE = "posthoc/mallory-agent.c3ead9ec.jar"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def attest(campaign: Path, calibration: Path) -> dict:
    result = json.loads((campaign / "result.json").read_text())
    config_bytes = (campaign / "config.json").read_bytes()
    config = json.loads(config_bytes)
    require(result["case_id"] == config["case_id"] == "ZOOKEEPER-01", "wrong case")
    require(result["status"] in ("budget_exhausted", "queue_exhausted"), "nonterminal campaign")
    require(config["target"]["check_sites"] == [CHECK], "check-site drift")
    require(config["target"]["throw_site"] == THROW, "throw-site drift")
    require(result["healthy_seed_valid"] is True, "invalid healthy seed")
    trial_rows = result["trials"]
    require(len(trial_rows) == result["fault_trials_completed"] + 1, "trial count mismatch")
    require([row["trial_id"] for row in trial_rows] == list(range(len(trial_rows))), "trial ID gap")

    compiled = (campaign / CLASS_ARCHIVE).read_bytes()
    compiled_sha = sha(compiled)
    require(compiled_sha == sha((calibration / "full-compiled-target.class").read_bytes()),
            "archived target class differs from original preserved class")
    source_archive = campaign / SOURCE_ARCHIVE
    require(sha(source_archive.read_bytes()) ==
            sha((calibration / "full-executed-source.tar.gz").read_bytes()),
            "archived source differs from original preserved source")
    with tarfile.open(source_archive, "r:gz") as archive:
        source_member = archive.extractfile(SOURCE)
        require(source_member is not None, "target source absent from snapshot")
        source_bytes = source_member.read()
    lines = source_bytes.decode().splitlines()
    require("if (session.isClosing())" in lines[318], "check source line drift")
    require("throw new KeeperException.SessionExpiredException()" in lines[319], "throw source line drift")
    require(sha((campaign / AGENT_ARCHIVE).read_bytes()) ==
            sha((calibration / "full-agent.jar").read_bytes()),
            "archived agent differs from original preserved jar")

    counts = {"target_reached": 0, "target_throw": 0, "effective_fault": 0,
              "target_lost": 0, "target_exception_candidate": 0}
    target_throw_trials = []
    loaded_classes = set()
    loader_sets = []
    for row in trial_rows:
        trial_id = row["trial_id"]
        directory = campaign / f"trials/r{trial_id:04d}"
        receipt = json.loads((directory / "result.json").read_text())
        feedback = receipt["feedback"]
        require(receipt["case_id"] == "ZOOKEEPER-01" and receipt["trial_id"] == trial_id,
                f"trial {trial_id} identity drift")
        require(feedback["status"] == row["status"], f"trial {trial_id} status mismatch")
        for key in ("all_faults_applied", "all_faults_effective", "all_faults_matched",
                    "target_reached", "target_exception_candidate"):
            require(feedback[key] == row[key], f"trial {trial_id} {key} mismatch")

        catalog_bytes = (directory / "sites.jsonl").read_bytes()
        require(sha(catalog_bytes) == receipt["site_catalog_sha256"],
                f"trial {trial_id} catalog SHA mismatch")
        catalog = [json.loads(s) for s in catalog_bytes.splitlines() if s.strip()]
        exact = {(entry["type"], entry["site"]): entry for entry in catalog}
        require(("TARGET_CHECK", CHECK) in exact and ("TARGET_THROW", THROW) in exact,
                f"trial {trial_id} exact sites missing")
        target_rows = [exact[("TARGET_CHECK", CHECK)], exact[("TARGET_THROW", THROW)]]
        require([entry["line"] for entry in target_rows] == [319, 320],
                f"trial {trial_id} source lines mismatch")
        require(all(entry.get("class_name") == TARGET_CLASS for entry in target_rows),
                f"trial {trial_id} target class mismatch")
        require(all(entry.get("bytecode_sha256") == compiled_sha for entry in target_rows),
                f"trial {trial_id} loaded class differs from archived compiled class")
        loaders = {entry.get("class_loader_id") for entry in target_rows}
        require(None not in loaders, f"trial {trial_id} class loader missing")
        require(len(loaders) == 1, f"trial {trial_id} ambiguous target class loader")
        loaded_classes.update(entry["bytecode_sha256"] for entry in target_rows)
        loader_sets.append(sorted(loaders))

        gz_bytes = (directory / "events.jsonl.gz").read_bytes()
        evidence = receipt["events_evidence"]
        require(sha(gz_bytes) == evidence["gzip_sha256"],
                f"trial {trial_id} compressed event SHA mismatch")
        raw = gzip.decompress(gz_bytes)
        require(sha(raw) == evidence["raw_sha256"] == receipt["events_sha256"],
                f"trial {trial_id} event SHA mismatch")
        events = [json.loads(s) for s in raw.splitlines() if s.strip()]
        checks = [e for e in events if e.get("type") == "TARGET_CHECK" and e.get("site") == CHECK]
        throws = [e for e in events if e.get("type") == "TARGET_THROW" and e.get("site") == THROW]
        last_fault_seq = feedback["last_fault_seq"]
        checks_after_fault = [e for e in checks if e["seq"] > last_fault_seq]
        throws_after_fault = [e for e in throws if e["seq"] > last_fault_seq]
        require(bool(checks_after_fault) == feedback["target_reached"],
                f"trial {trial_id} target reach mismatch")
        require(bool(throws_after_fault) == feedback["target_threw"],
                f"trial {trial_id} target throw mismatch")
        if feedback["target_reached"]:
            require(all(e.get("node") == result["target_binding"]["node"] for e in checks_after_fault),
                    f"trial {trial_id} target node mismatch")
            counts["target_reached"] += 1
        if throws_after_fault:
            counts["target_throw"] += 1
            target_throw_trials.append(trial_id)
        if feedback["all_faults_effective"]:
            counts["effective_fault"] += 1
        if feedback["status"] == "target_lost":
            counts["target_lost"] += 1
        if feedback["target_exception_candidate"]:
            require(bool(throws_after_fault), f"trial {trial_id} candidate lacks post-fault target throw")
            counts["target_exception_candidate"] += 1

    require(result["target_reached_trials"] == counts["target_reached"] - 1,
            "campaign target reach count mismatch")
    require(result["strict_injected_trials"] <= counts["effective_fault"],
            "campaign strict injection count exceeds effective fault trials")
    require(result["exact_exception_trials"] == counts["target_exception_candidate"],
            "campaign exact exception count mismatch")
    return {
        "schema_version": 1,
        "case_id": "ZOOKEEPER-01",
        "attestation": "passed",
        "campaign_status": result["status"],
        "campaign_result_sha256": sha((campaign / "result.json").read_bytes()),
        "campaign_config_sha256": sha(config_bytes),
        "source_snapshot_sha256": sha(source_archive.read_bytes()),
        "target_source_sha256": sha(source_bytes),
        "archived_compiled_target_path": CLASS_ARCHIVE,
        "archived_compiled_target_sha256": compiled_sha,
        "source_snapshot_path": SOURCE_ARCHIVE,
        "agent_jar_path": AGENT_ARCHIVE,
        "agent_jar_sha256": sha((campaign / AGENT_ARCHIVE).read_bytes()),
        "loaded_target_class_sha256": sorted(loaded_classes),
        "target_class_loader_per_trial": loader_sets,
        "exact_check_site": CHECK,
        "exact_throw_site": THROW,
        "counts": counts,
        "target_throw_trials": target_throw_trials,
        "trials_audited": len(trial_rows),
        "limitation": "The campaign predates the launch-time expected_target_class_sha256 gate; class identity was independently verified after execution against archived class bytes and every trial catalog.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    receipt = attest(args.campaign.resolve(), args.calibration.resolve())
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: receipt[k] for k in ("attestation", "campaign_status", "counts", "trials_audited")}))
