"""Copy completed isolated HBase calibrations with per-file receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

REPO = Path("/users/ZhenyuLi/baseline")
sys.path.insert(0, str(REPO))

from Mallory.dispatch.archive import TERMINAL, ensure
from Mallory.dispatch.core_release import verify as verify_release
from Mallory.dispatch.worker import atomic_json


DATA = REPO / "data/mallory"
REMOTE_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/hbase")
KEY = Path("/users/ZhenyuLi/.ssh/id_ed25519_nodes")
RELEASE_5820 = REPO / "Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf/manifest.json"
RELEASE_5A = REPO / "Mallory/dispatch/releases/5a35547d57dd66c29b15260f04cf52941b907e28bc07f0ceb0f1d4b3782c4040/manifest.json"
LANES = {
    "lane1-next": {"cohort": "v9", "cases": ("HBASE-14",),
                   "source_suffix": ""},
    "lane4": {"cohort": "v5", "cases": ("HBASE-08", "HBASE-13", "HBASE-04"),
              "source_suffix": ""},
    "lane5": {"cohort": "v6", "cases": ("HBASE-29", "HBASE-30"),
              "source_suffix": "-meta-cache"},
    "lane6": {"cohort": "v7", "cases": ("HBASE-11", "HBASE-19", "HBASE-20",
                                         "HBASE-21", "HBASE-22"),
              "source_suffix": "-alternate"},
    "lane6v2": {"cohort": "v8", "cases": ("HBASE-19", "HBASE-20",
                                           "HBASE-21", "HBASE-22"),
                "source_suffix": "-xerial"},
    "lane7": {"cohort": "v10", "cases": ("HBASE-24",),
              "source_suffix": "-v5b"},
    "lane9": {"cohort": "v11", "cases": ("HBASE-24",),
              "source_suffix": "-5a", "release": RELEASE_5A},
    "lane9-next": {"cohort": "v12", "cases": ("HBASE-23",),
                   "source_suffix": "-alt-5820-v1"},
    "lane9-next-r1": {"cohort": "v13", "cases": ("HBASE-23",),
                      "root_lane": "lane9-next", "source_suffix": "-alt-5820-repeat01"},
    "lane9-next-r2": {"cohort": "v14", "cases": ("HBASE-23",),
                      "root_lane": "lane9-next", "source_suffix": "-alt-5820-repeat02"},
    "lane9-next-r3": {"cohort": "v15", "cases": ("HBASE-23",),
                      "root_lane": "lane9-next", "source_suffix": "-alt-5820-repeat03"},
}
CORE_AUDIT_FILES = ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote_hashes(source: Path) -> dict[str, str]:
    code = (
        "import hashlib,json,pathlib,sys; "
        "root=pathlib.Path(sys.argv[1]); "
        "files=sorted(p for p in root.rglob('*') if p.is_file() and p.name!='.campaign.lock'); "
        "print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},sort_keys=True))"
    )
    result = subprocess.run(
        ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", "ZhenyuLi@node1",
         shlex.join(["python3", "-c", code, str(source)])],
        capture_output=True, text=True, check=True, timeout=120,
    )
    return json.loads(result.stdout)


def sync(case_id: str, release: dict, lane: str) -> dict:
    settings = LANES[lane]
    if case_id not in settings["cases"]:
        raise ValueError(f"{case_id} does not belong to {lane}")
    cohort = settings["cohort"]
    source = REMOTE_ROOT / settings.get("root_lane", lane) / f"healthy-{case_id}{settings['source_suffix']}"
    target = DATA / f"calibration_{cohort}" / case_id
    hashes = remote_hashes(source)
    if "result.json" not in hashes or "offline-causal-audit.json" not in hashes:
        raise ValueError(f"{case_id}: terminal result and audit are required")
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["rsync", "-a", "--exclude=.campaign.lock", "-e",
         f"ssh -i {KEY} -o IdentitiesOnly=yes",
         f"ZhenyuLi@node1:{source}/", f"{target}/"],
        check=True, timeout=300,
    )
    local = {str(path.relative_to(target)): digest(path)
             for path in sorted(target.rglob("*"))
             if path.is_file() and path.name != "calibration-receipt.json"}
    if hashes != local:
        raise ValueError(f"{case_id}: copied files differ from remote hashes")
    result = json.loads((target / "result.json").read_text())
    audit = json.loads((target / "offline-causal-audit.json").read_text())
    expected_core = {name: release["files"][f"Mallory/core/{name}"]
                     for name in CORE_AUDIT_FILES}
    if (result.get("case_id") != case_id
            or result.get("status") not in TERMINAL["calibration"]
            or audit.get("case_id") != case_id
            or audit.get("campaign_result_sha256") != hashes["result.json"]
            or audit.get("core_source_sha256") != expected_core):
        raise ValueError(f"{case_id}: terminal result or fixed-core audit mismatch")
    archive = ensure(DATA, "calibration", case_id, cohort=cohort)
    receipt = {
        "schema_version": 1, "case_id": case_id, "cohort": cohort,
        "source_host": "node1", "source_path": str(source),
        "status": result["status"],
        "result_sha256": hashes["result.json"],
        "audit_sha256": hashes["offline-causal-audit.json"],
        "remote_files_sha256": hashes,
        "archive_sha256": archive["archive_sha256"],
        "archive_manifest_sha256": archive["manifest_sha256"],
        "report_gate_passed": audit.get("report_gate_passed") is True,
        "healthy_observed_path_doors": audit.get("healthy_observed_path_doors"),
        "core_release_id": release["release_id"],
    }
    if lane == "lane9":
        receipt["healthy_local_timeline_doors"] = audit.get("healthy_local_timeline_doors")
        receipt["healthy_closure_evidence_types"] = audit.get("healthy_closure_evidence_types")
    if lane == "lane6v2":
        config = json.loads((target / "config.json").read_text())
        override = config.get("mapping", {}).get("codec_override", {})
        artifacts = {item["path"]: item["sha256"]
                     for item in config.get("runtime_artifacts", [])}
        conf = str(REMOTE_ROOT / lane / "runtime/conf/hbase-site.xml")
        jar = "/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-compression-snappy-2.6.6.jar"
        if (override.get("config_sha256") != artifacts.get(conf)
                or override.get("jar_sha256") != artifacts.get(jar)
                or override.get("key") != "hbase.io.compress.snappy.codec"
                or override.get("value")
                != "org.apache.hadoop.hbase.io.compress.xerial.SnappyCodec"):
            raise ValueError(f"{case_id}: codec override lacks pinned artifacts")
        receipt["codec_override"] = {
            "key": override["key"], "value": override["value"],
            "hbase_site_xml_sha256": override["config_sha256"],
            "xerial_jar_sha256": override["jar_sha256"],
        }
    atomic_json(target / "calibration-receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", choices=tuple(LANES))
    parser.add_argument("case_id")
    args = parser.parse_args()
    receipt = sync(args.case_id,
                   verify_release(LANES[args.lane].get("release", RELEASE_5820)),
                   args.lane)
    print(json.dumps({key: receipt[key] for key in
                      ("case_id", "status", "result_sha256", "audit_sha256",
                       "archive_sha256", "report_gate_passed", "healthy_observed_path_doors")},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
