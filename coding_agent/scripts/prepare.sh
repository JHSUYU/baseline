#!/usr/bin/env bash
# prepare.sh <case> [dir] -- make cases/<case>/agent/ (or [dir], without a prompt, for validation): a private copy of the system tree (git history removed,
# one commit "base"), its own dependency cache, env.sh, the agent's home, and the prompt.
# Inputs come from the Specula setup's targets and built trees (same check site, workload, base commit).
set -euo pipefail
case_id=${1:?usage: prepare.sh <case>}
# The known bugs at their buggy versions are copied from their built golden trees (bin/prepare_known.py).
if [[ ${case_id} == *-adhoc-k[0-9]* ]]; then exec python3 -I /bulk/codingagent/bin/prepare_known.py copy "$@"; fi
S=/bulk/specula-adhoc          # source of trees, caches, tools and targets
R=/bulk/codingagent
case ${case_id} in
  hdfs-*)  system=hdfs;      src=$S/src/hadoop;      tree=hadoop;      deps=$S/m2;           envsh=$S/env.sh ;;
  zk-*)    system=zookeeper; src=$S/src/zookeeper;   tree=zookeeper;   deps=$S/m2-zookeeper; envsh=$S/zookeeper-env.sh ;;
  hbase-*) system=hbase;     src=$S/src/hbase;       tree=hbase;       deps=$S/m2-hbase;     envsh=$S/hbase-env.sh ;;
  solr-*)  system=solr;      src=$S/src/lucene-solr; tree=lucene-solr; deps=$R/deps/ivy-solr; envsh=$S/solr-env.sh ;;   # Specula's Ivy cache, completed offline-ready (see README)
  *) echo "unknown case ${case_id}" >&2; exit 2 ;;
esac
dir=$R/cases/${case_id}
agent=${2:-${dir}/agent}
target=$S/${system}/targets/${case_id}.yaml
# A case-specific replacement of the target (e.g. another starting test), see overrides/.
[[ -f $R/overrides/${case_id}.yaml ]] && target=$R/overrides/${case_id}.yaml
[[ -f ${target} ]] || { echo "missing ${target}" >&2; exit 2; }
[[ -e ${agent}/${tree} ]] && { echo "${case_id}: already prepared"; exit 0; }
mkdir -p "${agent}/home/.claude" "${agent}/tmp" "${dir}/logs"
chmod 700 "${agent}/home/.claude"
cp -a "${src}" "${agent}/${tree}.partial"
# A ported workload is an untracked file of the case tree (the Specula setup's B3 port).
if [[ -d $S/${system}/workloads/${case_id}/tree && ! -e $R/overrides/${case_id}.no-port ]]; then
  cp -a "$S/${system}/workloads/${case_id}/tree/." "${agent}/${tree}.partial/"
fi
# No history: the agent sees one commit holding the base tree, nothing older or newer.
( cd "${agent}/${tree}.partial"
  # Keep the branch name (Lucene's build cleans every build dir when .git/HEAD changes).
  head=$(sed -n 's#^ref: refs/heads/##p' .git/HEAD); head=${head:-main}
  rm -rf .git
  git init -q -b "${head}"
  git -c user.name=base -c user.email=base@localhost add -A
  git -c user.name=base -c user.email=base@localhost commit -q -m "base" )
mv "${agent}/${tree}.partial" "${agent}/${tree}"
cp -a "${deps}" "${agent}/deps"
# Solr's lib/ symlinks point into the shared Ivy cache: repoint them at this case's own copy.
if [[ ${system} == solr ]]; then
  find "${agent}/${tree}" -type l -lname "$S/ivy-solr/*" -print0 | while IFS= read -r -d '' l; do
    t=$(readlink "$l"); ln -sfn "${agent}/deps/${t#$S/ivy-solr/}" "$l"; done
fi
T=/opt/tools   # JDKs, Maven and Ant from $S, mounted read-only here in the container
case ${system} in
  hdfs|zookeeper|hbase) cat > "${agent}/env.sh" <<ENV
# Build environment for ${tree}: source this file before building or running tests.
export JAVA_HOME=$T/jdk/jdk-17.0.21+9
export MAVEN_HOME=$T/apache-maven-3.9.15
export PATH=\$MAVEN_HOME/bin:\$JAVA_HOME/bin:\$PATH
export MAVEN_OPTS="-Xmx8g -Dmaven.repo.local=${agent}/deps"   # local repository with every dependency; builds run offline (mvn -o)
ENV
  ;;
  solr) cat > "${agent}/env.sh" <<ENV
# Build environment for ${tree} (Ant + Ivy, JDK 11): source this file before building or running tests.
export JAVA_HOME=$T/jdk/jdk-11
export ANT_HOME=$T/apache-ant-1.10.14
export PATH=\$ANT_HOME/bin:\$JAVA_HOME/bin:\$PATH
export IVY_USER_DIR=${agent}/deps   # Ivy cache with every dependency; pass ant -lib \$IVY_USER_DIR/lib
export ANT_OPTS="-Xmx4g -Divy.default.ivy.user.dir=\$IVY_USER_DIR"
ENV
  ;;
esac
[[ -n ${2:-} ]] || cp "${target}" "${dir}/target.yaml"
[[ -n ${2:-} ]] || python3 -I "$R/bin/make_prompt.py" "${dir}/target.yaml" "${agent}/${tree}" "${agent}/env.sh" "${agent}/result.json" > "${dir}/prompt.md"
echo "${case_id}: prepared ${agent}/${tree}"
