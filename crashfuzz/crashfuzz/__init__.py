"""CrashFuzz-style fault injection into systems' own cluster JUnit tests.

Modules, bottom up: ``trace`` (trace files, JSON helpers), ``faults`` (fault
point identity and matching), ``oracle`` (what a run says about the check),
``scheduler`` (which sequence next), ``campaign`` (one resumable campaign),
``selection`` (the Soot selection), ``runners`` (one JUnit per system),
``worker`` (a checklist case end to end), ``cluster`` and ``report``.
"""
