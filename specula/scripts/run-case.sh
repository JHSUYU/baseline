#!/usr/bin/env bash
# run-case.sh <case> [extra specula args] -- one Specula ad hoc run on a private copy of the tree.
#
# The system comes from the case id's prefix (hdfs-, zk-, hbase-, solr-).  Each case gets
# its own source tree and dependency cache, copied from the system's built master, so
# concurrent runs never see each other's instrumentation or installed jars.  The case's
# target file is <system>/targets/<case>.yaml with source_tree and build.env pointed
# at the copy.  Extra args go to `specula run` (e.g. --run-id=<id> to resume).
set -euo pipefail

case_id=${1:?usage: run-case.sh <case> [extra specula args]}
shift
root=/bulk/specula-adhoc
specula=/users/ZhenyuLi/Specula
model='claude-opus-5-5[1m]'   # pinned for all 84 runs

# One block per system: source tree, dependency cache, env.sh, repository.
# A block is filled in at that system's B1.
case ${case_id} in
  hdfs-*)
    system=hdfs
    src=${root}/src/hadoop
    tree=hadoop                # the case copy's directory name (the agents see it)
    deps=${root}/m2            # Maven repository
    envsh=${root}/env.sh
    repo=apache/hadoop
    ;;
  zk-*)
    system=zookeeper
    src=${root}/src/zookeeper   # apache/zookeeper eab16599, only that history (no remote, no newer refs)
    tree=zookeeper
    deps=${root}/m2-zookeeper
    envsh=${root}/zookeeper-env.sh
    repo=apache/zookeeper
    ;;
  hbase-*)
    system=hbase
    src=${root}/src/hbase       # apache/hbase 1790942bb2, only that history (no remote, no newer refs)
    tree=hbase
    deps=${root}/m2-hbase
    envsh=${root}/hbase-env.sh
    repo=apache/hbase
    ;;
  solr-*)
    system=solr
    src=${root}/src/lucene-solr   # apache/lucene-solr faca81bff1 (branch_8_11), only that history
    tree=lucene-solr
    deps=${root}/ivy-solr         # Ivy cache (and the Ivy jar under lib/)
    envsh=${root}/solr-env.sh
    repo=apache/lucene-solr
    ;;
  *) echo "unknown case prefix: ${case_id}" >&2; exit 2 ;;
esac

sysdir=${root}/${system}
dir=${sysdir}/cases/${case_id}
target=${sysdir}/targets/${case_id}.yaml
[[ -f ${target} ]] || { echo "missing ${target}" >&2; exit 2; }

if [[ ! -d ${dir} ]]; then
  mkdir -p "${dir}"
  # TLC memory cap of this case's run, fixed at creation so a resume keeps it.  24G lets 10
  # runs share the 376 GB host (2026-10-29); the first five HDFS runs have no file and keep 48G.
  echo 24G > "${dir}/tlc-memory-limit"
  cp -a "${src}" "${dir}/${tree}"
  cp -a "${deps}" "${dir}/deps"
  case ${system} in
    hdfs|zookeeper|hbase)
      sed -e "s#^export MAVEN_OPTS=.*#export MAVEN_OPTS=\"-Xmx8g -Dmaven.repo.local=${dir}/deps\"#" \
        "${envsh}" > "${dir}/env.sh"
      echo "export SPECULA_CASE_M2=${dir}/deps   # pass -Dmaven.repo.local=\$SPECULA_CASE_M2 if MAVEN_OPTS is overridden" >> "${dir}/env.sh"
      ;;
    solr)
      sed -e "s#^export IVY_USER_DIR=.*#export IVY_USER_DIR=${dir}/deps   # this case's Ivy cache; ant ... -Divy_install_path=\$IVY_USER_DIR/lib#" \
        "${envsh}" > "${dir}/env.sh"
      ;;
  esac
  # A ported workload (B3) is an untracked file of the case tree only.
  if [[ -d ${sysdir}/workloads/${case_id}/tree ]]; then
    cp -a "${sysdir}/workloads/${case_id}/tree/." "${dir}/${tree}/"
  fi
  sed -e "s#^source_tree: .*#source_tree: ${dir}/${tree}#" \
    -e "s#^  env: .*#  env: ${dir}/env.sh#" \
    "${target}" > "${dir}/target.yaml"
fi

cd "${specula}"
export PATH=${root}/jdk/jdk-21.0.13+9/bin:${root}/pybin:${HOME}/.local/bin:${PATH}
export JAVA_HOME=${root}/jdk/jdk-21.0.13+9
export DISABLE_AUTOUPDATER=1   # keep the pinned CLI version on every node
export CLAUDE_CODE_DISABLE_AUTO_MEMORY=1   # each run starts from its inputs only: no notes carried over from other runs
echo "Claude Code CLI: $(claude --version 2>&1 | head -1); model: ${model}"
# A resume (--run-id) reuses the run's stored artifact and target paths: Specula compares the
# target path as stored, and runs started before 2026-10-29 stored them under the old v2/ link.
paths=(--artifact="${dir}/${tree}" --adhoc-target="${dir}/target.yaml")
for a in "$@"; do [[ ${a} == --run-id=* ]] && paths=(); done
exec .venv/bin/specula run \
  "${case_id}|${repo}|Java|ad hoc coordination check (see the ad hoc target file)" \
  "${paths[@]}" \
  --model="${model}" \
  --max-repair-rounds=3 \
  --tlc-memory-limit="$(cat "${dir}/tlc-memory-limit" 2>/dev/null || echo 48G)" \
  "$@"
