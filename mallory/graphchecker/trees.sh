#!/usr/bin/env bash
# trees.sh <case id>...: the system tree each baseline case runs on, under GC_TREES (mallory/settings.py:
# MALLORY_GC_TREES), built for the case. A tree that is not there is cloned at its fork's baseline/mallory
# branch (the commit Mallory ran on); then GraphChecker's `run.sh <case> build` builds what the case's
# workload needs (its modules, and one run of its test for the classpath report). Run it on a host with
# Maven, after apply.sh made the system's checkout. The old-bug cases run on GraphChecker's own tree set
# of the buggy-detect branches (their trees.tsv and prepare-trees.sh), not on this one.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
settings() { (cd "${here}/.." && python3 -c "from mallory import settings; print($1)"); }
GC_TREES=$(settings 'settings.TREES') GC_M2=$(settings 'settings.M2')
export GC_TREES GC_M2
for id in "$@"; do
  checkout=$(settings "settings.system_of('${id}').checkout")
  source "${checkout}/experiments/lib/case-id.sh"
  read -r dir arg <<<"$(case_dir_of "${checkout}" "${id}")"
  [[ "${arg}" != - ]] || arg=""
  repo=$(bash -c 'source "$1" "$2" "$3" >/dev/null && echo "${repo}"' _ \
    "${checkout}/experiments/lib/case-env.sh" "${dir}" "${arg}")
  case ${id%%-*} in
    hdfs) fork=hadoop ;; hbase) fork=hbase ;; solr) fork=solr ;; zk) fork=zookeeper ;;
    *) echo "${id}: no fork for its system" >&2; exit 2 ;;
  esac
  if [[ ! -e "${repo}/.git" ]]; then
    mkdir -p "$(dirname "${repo}")"
    git clone -q --branch baseline/mallory --single-branch "https://github.com/JHSUYU/${fork}.git" "${repo}"
  fi
  echo "== ${id}: $(basename "${repo}") at $(git -C "${repo}" rev-parse --short HEAD), $(date +%T) on $(hostname)"
  (cd "${dir}" && bash "${checkout}/experiments/lib/run.sh" "${dir}" "${arg}" build)
  echo "== ${id}: built $(date +%T)"
done
