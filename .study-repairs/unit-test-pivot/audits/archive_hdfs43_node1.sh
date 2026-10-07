#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HDFS-43
offload_dir=/users/ZhenyuLi/baseline-evidence-offload/hdfs43-independent-20261007
mkdir -p "$offload_dir"
cd "$case_dir"

manifest="$offload_dir/raw-files.sha256"
archive="$offload_dir/raw-evidence.tar.zst"
temporary="$archive.tmp"
if [[ -e "$archive" || -e "$temporary" ]]; then
  echo 'archive already exists; refusing to overwrite' >&2
  exit 1
fi

find independent/evidence independent/equal_phase/evidence -type f -print0 \
  | sort -z | xargs -0 sha256sum > "$manifest"
tar -I 'zstd -T2 -3' -cf "$temporary" \
  independent/evidence independent/equal_phase/evidence
tar -I zstd -tf "$temporary" > /dev/null
mv "$temporary" "$archive"
sha256sum "$manifest" "$archive" > "$offload_dir/archive.sha256"
wc -l "$manifest"
du -h "$archive"
