# HDFS rollback completed plans 141–160 archive

The shared unchanged `TestDFSRollback#testRollback` campaign continued from
its atomic checkpoint while node2 archived completed plans 141–160. These
20 distinct plans were all strictly injected. At plan 160, HDFS-26 had
80 same-actor effective runs and HDFS-37 had 79.

The source archive contains 220 regular files and 174360887 original bytes.
Node2 extracted its zstd tar and checked every file's size and SHA-256 before
publishing the immutable manifest. Tar SHA-256:
`e5e3b69747c99fb9f0787a7c280d0d93cac2831beccd3242cdf25471621b8e0b`;
manifest SHA-256:
`d136f8720e910a4b5b9e9d805de0f5fc5aa49d486b134203a21099a86c20743a`.

Node1 restored and independently SHA-verified all 220 files; its receipt
SHA-256 is
`9617d63e90ed60046fc1670ae81892bc14261841a0128d8639ec0e4c68393159`.
Only then did node2 prune 55 verified regenerable scratch and coverage-export
files totaling 79671186 bytes. Raw traces, plans, JUnit logs, JaCoCo data,
manifests, and candidate evidence remained. The subsequent independent raw
audit passed for the then-current 162 completed plans: 162 strict, HDFS-26
80 effective, HDFS-37 81 effective, zero novel target signatures, zero issues.

Artifacts are under
`/users/ZhenyuLi/hdfs-storage-v2-later-a4f3ec05f0b5/evidence/rollback-constructor/archives/rollback-0141-0160.*`
on node2 and the verified node1 mirror. No completed plan or queue entry was
replayed or reset.
