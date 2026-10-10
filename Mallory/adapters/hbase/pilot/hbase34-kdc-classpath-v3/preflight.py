#!/usr/bin/env python3
"""Verify HBASE-34 v3 test-helper staging without starting Java or JUnit."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import socket
import sys
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / "hbase34-kdc-classpath-v2"
HELPER = "org/apache/hadoop/hbase/http/ssl/KeyStoreTestUtil.class"
ANCHOR = "org/apache/hadoop/hbase/security/token/SecureTestCluster.class"
TRIAL_CP = "{trial_dir}/hbase34-testclasses"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def sha(path: Path) -> str:
    require(path.is_file(), f"missing file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def classpath(command: list[str]) -> list[str]:
    require(command.count("-cp") == 1, "expected exactly one JVM classpath")
    return command[command.index("-cp") + 1].split(":")


def validate_v3_config(config: dict, parent: dict, pins: dict) -> None:
    expected = json.loads(json.dumps(parent))
    java = expected["command"]
    cp_index = java.index("-cp") + 1
    original_cp = classpath(java)
    require(original_cp[3].endswith("/api-all-1.0.0-M20.jar"),
            "parent Directory API placement changed")
    java[cp_index] = ":".join(original_cp[:3] + [TRIAL_CP] + original_cp[3:])
    expected["command"] = ["python3", str(HERE / "run_case.py"), "{trial_dir}"] + java
    expected["runtime_artifacts"] += [
        {"path": str(HERE / "run_case.py"),
         "sha256": pins["case_files"]["run_case.py"]},
        {"path": pins["helper_jar"]["path"],
         "sha256": pins["helper_jar"]["sha256"]},
    ]
    expected["revision"] = "HBASE-34-M20-BC1.82-hbase-http-helper-v3-healthy"
    expected["mapping"]["classpath_repair"] = (
        "v2 Directory API/BC pins plus byte-identical SecureTestCluster "
        "and pinned KeyStoreTestUtil in writable per-trial class directory")
    expected["mapping"]["status"] = "pending_environment_repair_healthy_only_v3"
    require(config == expected, "v3 changes more than the isolated helper repair")
    command = config["command"]
    cp = classpath(command)
    require(command[:3] == ["python3", str(HERE / "run_case.py"), "{trial_dir}"]
            and cp[3] == TRIAL_CP and
            cp.index(TRIAL_CP) < cp.index(
                "/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/*"),
            "writable trial classes must precede the test jar wildcard")
    require(command[-3:] == parent["command"][-3:] and
            config["budget"] == parent["budget"] and
            config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False,
            "unchanged healthy selector or gate changed")


def preflight(node1: bool = False) -> dict:
    pins = load(HERE / "manifest.json")
    require(pins["schema_version"] == 3 and pins["case_id"] == "HBASE-34",
            "wrong package manifest")
    for name, digest in pins["case_files"].items():
        require(sha(HERE / name) == digest, f"package file changed: {name}")
    require(sha(PARENT / "manifest.json") == pins["parent_manifest_sha256"] and
            sha(PARENT / "healthy.json") == pins["parent_config_sha256"] and
            sha(PARENT / "sites.json") == pins["parent_sites_sha256"] and
            (HERE / "sites.json").read_bytes() == (PARENT / "sites.json").read_bytes(),
            "v2 parent package or target sites changed")
    parent_spec = importlib.util.spec_from_file_location("hbase34_v2_preflight",
                                                  PARENT / "preflight.py")
    require(parent_spec is not None and parent_spec.loader is not None,
            "cannot load parent preflight")
    parent_module = importlib.util.module_from_spec(parent_spec)
    parent_spec.loader.exec_module(parent_module)
    parent_result = parent_module.preflight(node1)
    require(parent_result["status"] == "passed" and not parent_result["jvm_started"],
            "v2 static admission failed")

    config = load(HERE / "healthy.json")
    validate_v3_config(config, load(PARENT / "healthy.json"), pins)
    require(sha(Path(pins["helper_source"]["path"])) ==
            pins["helper_source"]["sha256"], "helper source changed")
    require(sha(Path(pins["anchor_source"]["path"])) ==
            pins["anchor_source"]["sha256"], "unchanged cluster fixture source changed")
    source = Path(pins["helper_source"]["path"]).read_text()
    anchor_source = Path(pins["anchor_source"]["path"]).read_text()
    require("getClasspathDir(Class<?> klass)" in source and
            'getResource(file)' in source and
            "private static Class<?> testRunnerClass = SecureTestCluster.class" in anchor_source,
            "per-trial classpath directory explanation changed")
    pom = pins["hbase_server_pom"]
    require(sha(Path(pom["path"])) == pom["sha256"] and
            "<artifactId>hbase-http</artifactId>" in Path(pom["path"]).read_text() and
            "<type>test-jar</type>" in Path(pom["path"]).read_text(),
            "HBase test-helper dependency source changed")
    for key, member in (("helper_jar", HELPER), ("anchor_tests_jar", ANCHOR)):
        item = pins[key]
        require(item["member"] == member and sha(Path(item["path"])) == item["sha256"],
                f"{key} jar changed")
        with zipfile.ZipFile(item["path"]) as archive:
            bytecode = archive.read(member)
            if key == "helper_jar":
                require(archive.namelist() == [HELPER],
                        "helper jar contains anything other than the pinned class")
        require(hashlib.sha256(bytecode).hexdigest() == item["class_sha256"] and
                bytecode[:4] == b"\xca\xfe\xba\xbe" and
                int.from_bytes(bytecode[6:8], "big") == item["class_major"] == 52,
                f"{key} class is not the pinned Java 8 bytecode")
    # The original helper calls the BC legacy certificate generator. Verify
    # that the pinned provider chosen by v2 has that symbol too.
    bcprov = next(path for path in parent_result["bc_jar_sha256"]
                  if path.endswith("/bcprov-jdk18on-1.82.jar"))
    with zipfile.ZipFile(bcprov) as archive:
        require("org/bouncycastle/x509/X509V1CertificateGenerator.class" in
                archive.namelist(), "selected BC provider lacks the helper API")
    for explicit in classpath(config["command"])[:3]:
        with zipfile.ZipFile(explicit) as archive:
            require(HELPER not in archive.namelist() and ANCHOR not in archive.namelist(),
                    "an earlier runtime jar shadows trial-local classes")

    failure = pins["v2_failure"]
    if node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        path = Path("/users/ZhenyuLi/baseline/data/mallory/calibration_hbase34_kdc_classpath_v2/HBASE-34/trials/r0000/stderr.log")
        require(sha(path) == failure["node1_raw_stderr_sha256"],
                "v2 node1 stderr changed")
        stderr = path.read_text(errors="replace")
    else:
        for path_key, digest_key in (("archive_path", "archive_sha256"),
                                     ("archive_manifest_path", "archive_manifest_sha256"),
                                     ("receipt_path", "receipt_sha256"),
                                     ("node0_excerpt_path", "sha256")):
            require(sha(Path(failure[path_key])) == failure[digest_key],
                    f"sealed v2 failure changed: {path_key}")
        stderr = Path(failure["node0_excerpt_path"]).read_text(errors="replace")
    require(failure["signature"] in stderr and failure["frame"] in stderr and
            "MALLORY_JUNIT found=0 succeeded=0 failed=0" in stderr,
            "v2 failure is not the pinned missing test helper")
    sys.path.insert(0, str(Path(config["core_release"])))
    from Mallory.core.campaign import validate_config
    validate_config(config)
    return {"case_id": "HBASE-34", "status": "passed",
            "kind": "isolated_HBase_HTTP_helper_static_admission",
            "jvm_started": False, "runtime_validated": False,
            "v2_failure_verified": True,
            "helper_jar_sha256": pins["helper_jar"]["sha256"],
            "per_trial_classpath": TRIAL_CP}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node1", action="store_true")
    args = parser.parse_args()
    print(json.dumps(preflight(args.node1), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
