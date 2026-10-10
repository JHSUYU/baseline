# HDFS-29 scheduler-depth-reserve full v4

Immutable successor to v3. The original cluster JUnit, target, source, bytecode, fault sites and 80/3600/max3 budget are unchanged. Controller release 224e15f3a987faab681ec46278650cca80ee3bc34b75ea2f68c87b911f9928f1 was built from core including scheduler commit 12018488. The default policy periodically selects an available depth>1 plan after replay and validated-site rules. Graph/path and selected exception remain outcomes.

Launch only after predecessor full terminal and a fresh node2 lock/JVM/source/disk/output gate. This package has a distinct v4 output and does not mutate v3.
