#!/usr/bin/env bash
set -euo pipefail

port_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$port_dir/../.." && pwd)"
upstream="$repo_dir/GraphChecker"
expected_commit=c4a90033c654737206466ed36ce837c5b3c12457

test "$(git -C "$upstream" rev-parse HEAD)" = "$expected_commit"
for name in Corpus ClosurePlanner Branches; do
  cmp "$upstream/src/main/java/edu/uva/liftlab/graphchecker/explore/$name.java" \
    "$port_dir/src/main/java/edu/uva/liftlab/graphchecker/explore/$name.java"
done
printf '%s  %s\n' \
  8897901dee05750e9aa456978091190337aa3762a813527fbd510ff8d3c38880 "$upstream/target/GraphChecker-1.0-SNAPSHOT.jar" \
  222f2d74236d432c6ad4001f5d9423b5bd9567084ad668089676ccf8de43e343 "$upstream/target/GraphChecker-1.0-SNAPSHOT-jar-with-dependencies.jar" \
  | sha256sum --check --status
printf 'GraphChecker source and jar provenance verified at %s\n' "$expected_commit"
