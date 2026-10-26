#!/usr/bin/env bash
# apply.sh <GraphChecker clone> <system> [<checkout dir>]: the GraphChecker checkout Mallory runs a
# system's cases on. It adds a worktree of the clone at the base commit bases.tsv pins for <system>
# (hdfs, hbase, solr or zookeeper: GraphChecker's system/<system>-cloudlab when Mallory ran), applies
# common/*.patch and systems/<system>/*.patch as branch mallory-<system>, and builds the jar.
# The checkout defaults to /bulk/wt/gc-mallory-<system>, where mallory/settings.py looks for it.
set -euo pipefail
clone=${1:?usage: apply.sh <GraphChecker clone> <system> [<checkout dir>]}
system=${2:?usage: apply.sh <GraphChecker clone> <system> [<checkout dir>]}
checkout=${3:-/bulk/wt/gc-mallory-${system}}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
base=$(awk -F'\t' -v s="${system}" '$1 == s {print $2}' "${here}/bases.tsv")
[[ -n "${base}" ]] || { echo "no base commit for ${system} in bases.tsv" >&2; exit 2; }

git -C "${clone}" fetch -q origin "system/${system}-cloudlab"
git -C "${clone}" worktree add -q -b "mallory-${system}" "${checkout}" "${base}"
git -C "${checkout}" am -q "${here}"/common/*.patch
if compgen -G "${here}/systems/${system}/*.patch" > /dev/null; then
  git -C "${checkout}" am -q "${here}/systems/${system}"/*.patch
fi
(cd "${checkout}" && mvn -q -DskipTests package)
echo "${checkout}: $(git -C "${checkout}" log --oneline -1)"
