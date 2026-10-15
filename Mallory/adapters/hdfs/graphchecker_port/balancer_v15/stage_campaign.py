"""Derive an independent K8/max12 HDFS campaign from byte-pinned V14 inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("/dev/shm/mallory-hdfs-balancer-v15b-node0")
V14 = ROOT / "inputs/prior-campaign-config-v14.json"
OVERLAY = Path("/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-monitor-v3-combined/overlay")
ENGINE = ROOT / "inputs/original-engine-5828ea86-catalog.jar"
ADAPTER = ROOT / "inputs/native-adapter-5828ea86.jar"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    assert json.loads((ROOT / "static-result-v15.json").read_text())["return_code"] == 0
    assert json.loads((ROOT / "weave-result-v15.json").read_text())["return_code"] == 0
    for name in ("healthy1", "healthy2"):
        result = json.loads((ROOT / name / "result.json").read_text())
        assert result["return_code"] == 0 and result["stop_reason"] is None
        assert (ROOT / name / "trace/streaming_trace_manifest.json").is_file()
    assert sha(V14) == "ac318753d1eba1b0e54981f5380c5a32849d0a0a598ff1d76367e1cc9883d260"
    config = json.loads(V14.read_text())
    assert config["case_id"] == "HDFS-11-TIMING-LIFETIME-REPEATED-RPC-V1"
    assert config["budget"]["max_faults_per_trial"] == 12
    assert config["recording"]["multi_target_max_anchors"] == 4
    config["case_id"] = "HDFS-11-TIMING-MONITOR-K8-REPEATED-RPC-V15"
    config["native_weave_config"] = str(ROOT / "inputs/native-weave-config-v15b.json")
    rec = config["recording"]
    rec.update({
        "analysis_engine_jar": str(ENGINE),
        "analysis_engine_sha256": sha(ENGINE),
        "candidate_graph": str(ROOT / "original-scope/candidate_dataflow_edges.jsonl.gz"),
        "region_skeletons": str(ROOT / "original-scope/region_skeletons.jsonl.gz"),
        "static_scope_map": str(ROOT / "original-scope/static_scope_map.jsonl"),
        "static_may_scope_map": str(ROOT / "static-scope/static_scope_map.jsonl"),
        "static_may_scope_map_sha256": sha(ROOT / "static-scope/static_scope_map.jsonl"),
        "trace_dir": str(ROOT / "healthy1/trace"),
        "target_name": "HDFS11TIMINGMONITORK8V15",
        "multi_target_max_anchors": 8,
    })
    old = config["runner"]["classpath"]
    runner = config["runner"]
    runner["classpath"] = [str(ROOT / "woven"), str(OVERLAY), str(ENGINE),
                            str(ADAPTER)] + [p for p in old if p not in old[:4]
                                                  and "native-fault-adapter" not in p]
    assert all(Path(p).exists() for p in runner["classpath"])
    runner["jvm_args"] = [*runner["jvm_args"],
                          "-Dmallory.gc.nativeFaultDoorContext=true"]
    runner["local_artifact_root"] = "/run/user/20003/mallory-hdfs-balancer-v15b-raw"
    runner["local_work_root"] = str(ROOT / "trial-work")
    for name in ("candidate_graph", "region_skeletons", "static_scope_map",
                 "static_may_scope_map", "trace_dir"):
        assert Path(rec[name]).exists(), name
    path = ROOT / "inputs/campaign-config-v15.json"
    assert not path.exists()
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    receipt = {"config": str(path), "config_sha256": sha(path),
               "parent_config_sha256": sha(V14),
               "combined_source_pin_sha256": sha(Path(
                   "/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-monitor-v3-combined/combined-source-build-pin-v1.json")),
               "engine_sha256": sha(ENGINE), "adapter_sha256": sha(ADAPTER),
               "static_map_sha256": sha(Path(rec["static_may_scope_map"])),
               "weave_receipt_sha256": sha(ROOT / "woven/native-original-weave-receipt.json"),
               "healthy1_manifest_sha256": sha(ROOT / "healthy1/trace/streaming_trace_manifest.json"),
               "healthy2_manifest_sha256": sha(ROOT / "healthy2/trace/streaming_trace_manifest.json"),
               "zero_imported_fault_trials": True, "manual_fault_site_overrides": 0}
    (ROOT / "inputs/campaign-pin-v15.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
