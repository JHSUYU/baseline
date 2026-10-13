#!/usr/bin/env bash
# Apply Mallory's causal transport hooks to a clean Solr 8.11.4 source tree.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <clean-solr-source-tree> [--check]" >&2
  exit 2
fi

source_tree=$(realpath "$1")
mode=${2:-apply}
if [[ "$mode" != apply && "$mode" != --check ]]; then
  echo "unknown mode: $mode" >&2
  exit 2
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
patch_file="$script_dir/solr-e27f44e-mallory-causal.patch"
expected=e27f44e3d78dfcec230c97e0a1240e3751daeff9
observed=$(git -C "$source_tree" rev-parse HEAD)
if [[ "$observed" != "$expected" ]]; then
  echo "Solr source HEAD $observed differs from inventory pin $expected" >&2
  exit 2
fi

# The patch owns only these files.  Other unrelated changes in an isolated
# checkout need not prevent this adaptation.
paths=(
  solr/common-build.xml
  solr/core/src/java/org/apache/solr/cloud/OverseerTaskProcessor.java
  solr/core/src/java/org/apache/solr/cloud/OverseerTaskQueue.java
  solr/core/src/java/org/apache/solr/cloud/ZkDistributedQueue.java
  solr/core/src/java/org/apache/solr/servlet/SolrDispatchFilter.java
  solr/solrj/build.xml
  solr/solrj/src/java/org/apache/solr/client/solrj/impl/Http2SolrClient.java
  solr/solrj/src/java/org/apache/solr/client/solrj/impl/HttpSolrClient.java
  solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java
  solr/solrj/src/java/org/apache/solr/common/util/MalloryHttp.java
  solr/test-framework/src/java/org/apache/solr/cloud/MiniSolrCloudCluster.java
)
if [[ -n $(git -C "$source_tree" status --porcelain -- "${paths[@]}") ]]; then
  echo "Solr causal patch paths have local changes; use a clean worktree" >&2
  exit 2
fi

git -C "$source_tree" apply --check "$patch_file"
if [[ "$mode" == --check ]]; then
  echo "Mallory Solr causal patch applies cleanly"
else
  git -C "$source_tree" apply "$patch_file"
  echo "Applied Mallory Solr causal patch"
fi
