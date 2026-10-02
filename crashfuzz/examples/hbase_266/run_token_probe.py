"""Test whether the real-cluster token RPC can reach allKeys.get(keyId)."""

from dataclasses import replace
import json
import os
from pathlib import Path

from adhoc_crashfuzz.campaign import Campaign, Settings
from adhoc_crashfuzz.model import FaultSequence, TargetSpec


HERE = Path(__file__).resolve().parent


def main() -> None:
    row = json.loads((HERE / "token_target.json").read_text())
    properties = dict(line.split("=", 1) for line in
                      (HERE / "agent.properties").read_text().splitlines()
                      if "=" in line)
    classes = set(properties["include.classes"].split(","))
    methods = set(properties["method.rules"].split(","))
    for method in [row["agent_method"]] + row["writer_methods"]:
        classes.add(method.split("#", 1)[0])
        methods.add(method.split("(", 1)[0])
    properties["include.classes"] = ",".join(sorted(classes))
    properties["method.rules"] = ",".join(sorted(methods))
    properties["point.entries"] = row["agent_method"]
    properties["target.guard"] = row["target_guard"]
    properties["target.throw"] = row["target_throw"]
    out = HERE / "out_token_probe"
    out.mkdir(exist_ok=True)
    config = out / "agent.properties"
    config.write_text("\n".join(key + "=" + value for key, value
                                in properties.items()) + "\n")
    os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(config.resolve())
    settings = Settings.from_file(HERE / "campaign.json")
    settings.backend.workload_command = ["python3", "token_workload.py"]
    settings.backend.check_command = []
    settings.backend.workload_timeout_s = 180
    settings = replace(settings, target=TargetSpec(row["target_guard"]),
                       output_dir=out)
    trial = Campaign(settings)._trial(FaultSequence(), "token")
    client_stderr = (out / "runs" / trial.run_id / "token-probe.stderr")
    diagnostic = client_stderr.read_text() if client_stderr.exists() else ""
    if "No registered coprocessor service found for AuthenticationService" in diagnostic:
        blocked_at = "authentication_service_not_registered"
    elif "No secret manager configured for token authentication" in diagnostic:
        blocked_at = "token_secret_manager_not_configured"
    elif "Token generation only allowed for Kerberos authenticated clients" in diagnostic:
        blocked_at = "token_generation_requires_kerberos"
    else:
        blocked_at = "" if trial.workload.returncode == 0 else "unclassified_client_error"
    result = {
        "site_id": row["site_id"], "guard": row["target_guard"],
        "throw": row["target_throw"],
        "run_id": trial.run_id,
        "workload_returncode": trial.workload.returncode,
        "target_reached": trial.closure.reached,
        "target_fatal": trial.closure.fatal,
        "blocked_at": blocked_at,
        "workload_stdout_tail": trial.workload.stdout[-1500:],
        "workload_stderr_tail": trial.workload.stderr[-1500:],
    }
    (HERE / "token_probe_result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
