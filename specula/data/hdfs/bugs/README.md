# HDFS: TLC files of every reproduced finding with a counterexample

One folder per model-checking finding that Specula reproduced in the real system (62 folders). Each holds:
- the specification modules;
- the config that produced the counterexample;
- the counterexample log;
- a `RERUN.md` with the TLC command (jars pinned in `../../../tlc/`).

The "Checked" line in each `RERUN.md` is the rerun of that config on the pinned TLC.

**Which of these are real, severe bugs that make the ad hoc check fail** is decided in `../VERIFIED-BUGS.md`:
- the decision was made by reading the source;
- tier A: 07/MC-1, 11/MC-4, 38/MC-1, 24/MC-2, 08/MC-1;
- tier B: 08/MC-2, 24/CR-6, 24/MC-3, 11/MC-1, 14/MC-1, 26/MC-1.

The other folders are findings that are duplicates, already known, by design, or not severe. See `../VERIFIED-BUGS.md` ("Dropped") and `../CLASSIFICATION*.md` / `../VERIFY-*.md`. Code-review findings have no TLC counterexample and are not here.
