# Producer cause propagation audit

This audit concerns the unchanged Solr source used for the SOLR-40
exploratory run. It does not change a running campaign or admit a new fault.

## Existing exact handoffs

- `MalloryHttp.prepareRequest` makes an HTTP GraphChecker envelope with a
  `solr-<counter>` correlation. `MessageDoors.prepareOutbound` puts the exact
  producer endpoint in the header; `MessageDoors.inbound` attaches it to the
  receiver. `producerReplayEndpointId` is derived from the current replay
  occurrence and a per-run send ordinal. These prove a within-run WIRE edge,
  but neither counter is a stable business message ID across trials.
- `CollectionsHandler.sendToOCPQueue` serializes `ZkNodeProps` as bytes. Its
  synchronous path calls `OverseerTaskQueue.offer(byte[], long)` and has no
  `ASYNC` request ID. The asynchronous path calls a different, one-argument
  `offer` after checking and claiming the caller's `ASYNC` ID. The r0006
  selected two-argument door is in the synchronous path.
- The synchronous `offer` allocates a ZooKeeper response node and then a
  request node. Their sequential path and `mzxid` exist only after the offer
  starts, so they cannot identify its pre-write fault door across runs.
- The existing Solr overlay preserves `path@mzxid` and the bytes obtained by
  the same `getData` on the consumer. `MessageDoors.stored/fetched` validates
  the payload digest and joins the exact writer/read endpoints when there is
  one observed writer. This is a within-run state/queue causal edge. The
  current `fetched` switches to that writer's exact endpoint cause but does
  not set a stable `replayCause` for subsequent consumer doors.
- `MessageDoors.prepareTask/claimTask` is a one-use in-process executor
  ticket. It carries an exact submit→claim edge but is neither serialized
  into the HTTP header nor the ZooKeeper queue item.

## Replay admission consequence

The isolated payload-key patch hashes real `offer` bytes and the queue route,
and requires one seed and one faulted occurrence with the same site, type,
payload key, and causal parent. It can admit actor migration only when the
causal context and structural parent also agree. Frozen r0006 has nine
faulted hits at the same queue-offer site on another actor and zero hits with
the seed's full static ancestry; the old traces carry no payload key. No
source-backed rule can identify one of those nine as the selected message.
The patch leaves all six old unmatched trials unchanged and may still reject
a fresh r0006-like run.

To propagate replay identity through HTTP → queue → consumer generically,
the producer must supply a stable operation/message ID before transport, or
the exact serialized bytes must be unique at both producer and consumer and
the same causal parent must be independently proven. The runtime may carry
that value in a separate replay field of an HTTP envelope and through a
confirmed queue write/read; it must retain the existing exact endpoint IDs
for the within-run graph. Duplicate, absent, changed, or conflicting IDs
must stay unmatched. The current synchronous Solr source provides no such
stable operation ID, and reading a streaming HTTP entity to invent one would
change workload behavior. Therefore this audit makes no further runtime or
adapter change and does not relax the causal-parent check.

## Source pins

- `CollectionsHandler.java` SHA-256
  `61be10aac1753a0defa3dcdfecf7109dd0ddc52669bdf0f1d3fa60e484d216ca`.
- Base `OverseerTaskQueue.java` SHA-256
  `96832609c3c01cf0f0b58ffb7ceeb7c0e45b74b6681a212f75f240062abc1385`.
- Solr causal overlay patch SHA-256
  `26c06960a8301af9b5e404330bcc4496c04eac058e46f76e19ebe072ef99d593`.
- HTTP operation hint patch SHA-256
  `c583c7c9357c9997d25d074ff2c2efaff901753fecb7f6f1b664da11f82ac9cc`.
- Runtime `MessageDoors.java` at this isolated commit SHA-256
  `6330e9d03f919a40eced01672a3a220732c98d328157376933800c67120ca98e`.
