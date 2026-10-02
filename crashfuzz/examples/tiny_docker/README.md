# Real two-container integration fixture

This fixture validates the Docker controller, Java 8 agent, cross-process
message edges, crash-point durability, target observation, and replay before
attaching a production system. It is a protocol fixture, not an HBase result.

From `baseline/crashfuzz` run:

```bash
cd agent && mvn -q -DskipTests package && cd ..
PYTHONPATH=src python3 -m adhoc_crashfuzz.cli run \
  --config examples/tiny_docker/campaign.json
```

The fixture uses `sudo -n docker` and the local
`causynth-openjdk8-build:ubuntu18` image. Container names and a Docker network
are prefixed `adhocfuzz-tiny`. `prepare.py` resets the containers for every
trial; `docker stop/start` during a trial leaves that container's filesystem
state intact. The result is under `examples/tiny_docker/out`.

To remove the fixture containers and network after the campaign:

```bash
sudo -n docker rm -f adhocfuzz-tiny-a adhocfuzz-tiny-b
sudo -n docker network rm adhocfuzz-tiny
```
