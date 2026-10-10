#!/usr/bin/env python3
"""Read-only release and Solr fixture preflight for one v2 healthy run."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

import preflight_stage

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V1_PACKAGE = HERE.parent / "healthy-watcher-handoff-node0-v1"
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def main() -> dict:
    # The earlier immutable package pins unchanged JUnit, source revision,
    # compiled Solr bytecode, node bindings, and all external runner inputs.
    spec = importlib.util.spec_from_file_location("solr40_v1_preflight", V1_PACKAGE / "preflight.py")
    prior = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prior)
    prior.main()
    preflight_stage.main()
    config_path = HERE / "config.json"
    config = json.loads(config_path.read_text())
    manifest = json.loads((HERE / "release-manifest.json").read_text())
    release = HERE / "releases/mallory-agent.jar"
    require(config["revision"] == "SOLR-40-healthy-exact-reference-handoff-node0-v2" and
            config["case_id"] == "SOLR-40" and
            config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["budget"]["trials"] == 1 and
            config["admission"]["full_promotion"] is False and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False,
            "v2 healthy-only or strict graph policy changed")
    require(config["agent_jar"] == str(release) and
            config["env"]["MALLORY_SOLR_AGENT_JAR"] == str(release) and
            config["site_file"] == str(HERE / "sites.json") and
            config["command"][1] == str(HERE / "run_pilot_v2.py"),
            "v2 exact-reference runtime path changed")
    require(release.is_file() and sha(release) ==
            manifest["agent_jar_sha256"] == config["mapping"]["agent_sha256"] and
            sha(HERE / "exact-reference-field.patch") == manifest["patch_sha256"] and
            sha(config_path) == manifest["config_sha256"] and
            sha(HERE / "sites.json") == manifest["sites_sha256"] and
            sha(HERE / "gate_v2.py") == manifest["gate_sha256"] and
            sha(HERE / "call_return.py") == manifest["call_return_sha256"] and
            sha(HERE / "run_pilot_v2.py") == manifest["pilot_runner_sha256"],
            "v2 release or package digest changed")
    for name, digest in manifest["source_base_sha256"].items():
        subdir = "test" if name.endswith("Test.java") else "main"
        source = (ROOT / "Mallory/instrumentation/src" / subdir / "java"
                  / "edu/uva/liftlab/mallory/instrumentation" / name)
        require(source.is_file() and sha(source) == digest,
                f"v2 isolated agent base source changed: {source}")
    with tempfile.TemporaryDirectory(prefix="solr40-v2-source-preflight-") as temp:
        for name in manifest["source_base_sha256"]:
            subdir = "test" if name.endswith("Test.java") else "main"
            relative = (Path("Mallory/instrumentation/src") / subdir / "java"
                        / "edu/uva/liftlab/mallory/instrumentation" / name)
            destination = Path(temp) / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        subprocess.run(["git", "apply", str(HERE / "exact-reference-field.patch")],
                       cwd=temp, check=True, capture_output=True)
        for name, digest in manifest["patched_source_sha256"].items():
            subdir = "test" if name.endswith("Test.java") else "main"
            relative = (Path("Mallory/instrumentation/src") / subdir / "java"
                        / "edu/uva/liftlab/mallory/instrumentation" / name)
            require(sha(Path(temp) / relative) == digest,
                    f"v2 patched source digest changed: {name}")
    request = json.loads((HERE / "admission-request.json").read_text())
    require(request.get("go") is False and
            request.get("full_campaign_go") is False and
            request.get("host") == "node0" and request.get("mode") == "healthy" and
            request.get("config_sha256") == sha(config_path) and
            request.get("agent_jar_sha256") == sha(release) and
            request.get("runner_sha256") == sha(HERE / "run_healthy_v2.py") and
            request.get("intended_output") == str(
                ROOT / "data/mallory/calibration_solr40_reference_handoff_v2_node0/SOLR-40") and
            request.get("admission_receipt") == str(HERE / "admission-healthy-node0.json") and
            sha(HERE / "admission-request.json") == manifest["admission_request_sha256"] and
            sha(HERE / "run_healthy_v2.py") == manifest["healthy_runner_sha256"] and
            sha(HERE / "audit_v2.py") == manifest["post_audit_sha256"],
            "healthy-only admission request or post-audit changed")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        require(path.is_file() and sha(path) == artifact["sha256"],
                f"v2 runtime artifact changed: {path}")
    with zipfile.ZipFile(release) as archive:
        for clazz, member, symbols in (
                ("Probe.class", "edu/uva/liftlab/mallory/instrumentation/Probe.class",
                 (b"stateReadObject", b"stateWriteObject", b"value_object", b"reference_value")),
                ("MalloryTransformer.class",
                 "edu/uva/liftlab/mallory/instrumentation/MalloryTransformer.class",
                 (b"stateReadObject", b"stateWriteObject"))):
            data = archive.read(member)
            require(hashlib.sha256(data).hexdigest() == manifest["agent_class_sha256"][clazz]
                    and all(symbol in data for symbol in symbols),
                    f"v2 class or reference hook changed: {clazz}")
    test_counts = {key: 0 for key in ("tests", "errors", "failures", "skipped")}
    for name, digest in manifest["maven_agent_test_report_sha256"].items():
        report = HERE / "releases/test-reports" / name
        require(report.is_file() and sha(report) == digest,
                f"isolated agent test report changed: {report}")
        root = ET.parse(report).getroot()
        for key in test_counts:
            test_counts[key] += int(root.attrib.get(key, 0))
    require(test_counts == manifest["maven_agent_test_counts"] ==
            {"tests": 26, "errors": 0, "failures": 0, "skipped": 0},
            "isolated agent Maven tests are not green")
    sys.path.insert(0, str(PINNED))
    from Mallory.core import campaign  # noqa: E402
    require(Path(campaign.__file__).resolve().is_relative_to(PINNED),
            "campaign core is not pinned")
    campaign.validate_config(config)
    receipt = {"status": "offline_runtime_preflight_passed", "case_id": "SOLR-40",
               "junit_launched": False, "healthy_only": True, "full_campaign_go": False,
               "agent_jar_sha256": sha(release), "config_sha256": sha(config_path)}
    print(json.dumps(receipt, sort_keys=True))
    return receipt


if __name__ == "__main__":
    main()
