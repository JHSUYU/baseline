#!/usr/bin/env python3
"""Reserve trial 2 on node1 after the Solr and actor-V2 owners release it.

Run on node0 only. This does not start a JVM. A marker on node2 blocks its
normal resume script until node1's single-trial result is reconciled.
"""

import json
from pathlib import Path
import subprocess
import sys


USER = "ZhenyuLi"
KEY = str(Path.home() / ".ssh/id_ed25519_nodes")
ROOT = "/users/ZhenyuLi/hdfs54-original-campaign/runs"
EXPECTED_SHA256 = "8728827521d8d650325f9801add8d15ba32dd38e3b458860f0ce1029ed256cf8"
FIRST_ID = "01f09073125e7810"


def remote(node, program):
    command = ["ssh", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o",
               "ConnectTimeout=8", f"{USER}@{node}", "python3", "-"]
    result = subprocess.run(command, input=program, text=True,
                            capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{node} rc={result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def inspect(node):
    program = f"""
import hashlib,json,pathlib,subprocess
p=pathlib.Path({ROOT!r})/'campaign-state.json'
raw=p.read_bytes();state=json.loads(raw)
active=subprocess.run(['tmux','has-session','-t',
                       {'hdfs54_original_80' if node == 'node2' else 'hdfs54_original_node1_pilot'!r}],
                      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
print(json.dumps({{'sha256':hashlib.sha256(raw).hexdigest(),
                  'effective':state['effective'],'attempts':len(state['attempts']),
                  'queue':len(state['queue']),'in_flight':state['in_flight'],
                  'first_id':state['attempts'][0]['id'],'active':active}}))
"""
    return json.loads(remote(node, program))


def reserve(node, name, payload):
    program = f"""
import json,pathlib
p=pathlib.Path({ROOT!r})/{name!r}
with p.open('x') as stream:
    json.dump({payload!r},stream,sort_keys=True)
    stream.write('\\n')
print(p)
"""
    return remote(node, program)


def main():
    if subprocess.check_output(["hostname", "-s"], text=True).strip() != "node0":
        raise RuntimeError("Run the two-host reservation from node0")
    states = {node: inspect(node) for node in ("node2", "node1")}
    for node, state in states.items():
        assert state == {"sha256": EXPECTED_SHA256, "effective": 1,
                         "attempts": 1, "queue": 31, "in_flight": None,
                         "first_id": FIRST_ID, "active": False}, (node, state)
    print("Both hosts have the same unchanged 1/80 checkpoint; reserving node1 trial 2")
    print(reserve("node2", ".node1-pilot-active",
                  {"owner": "node1-one-trial", "checkpoint_sha256": EXPECTED_SHA256}))
    print(reserve("node1", ".node1-pilot-lease.json",
                  {"owner": "node1-one-trial", "checkpoint_sha256": EXPECTED_SHA256}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"reservation failed closed: {error}", file=sys.stderr)
        raise SystemExit(1)
