# Legacy Mallory pilot evidence

`zk11-small-campaign-20261010.tar.zst` is the complete, terminal
`ZOOKEEPER-11` pilot formerly stored under
`Mallory/instrumentation/target/pilots/zk11-small-campaign/`. It is separate
from the current `data/mallory/campaigns/ZOOKEEPER-11-epoch-full-v2/` run.
The manifest records the SHA-256 and size of all 158 regular files. The
reclaim receipt records the archive and manifest SHA-256 values, the exact
source path, a zero-reference process scan, and disk space before and after
removal. The archive was unpacked and every member checked before removal.

To restore a verified copy, run from the repository root:

```sh
export MALLORY_LEGACY_RESTORE_DIR="$(mktemp -d)"
tar -I zstd -xf data/mallory/evidence_archives/legacy/zk11-small-campaign-20261010.tar.zst \
  -C "$MALLORY_LEGACY_RESTORE_DIR"
python3 - <<'PY'
import hashlib, json, os
from pathlib import Path

root = Path('data/mallory/evidence_archives/legacy')
manifest_path = root / 'zk11-small-campaign-20261010.manifest.json'
archive = root / 'zk11-small-campaign-20261010.tar.zst'
receipt = json.loads((root / 'zk11-small-campaign-20261010.reclaim-receipt.json').read_text())
manifest = json.loads(manifest_path.read_text())
assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == receipt['manifest_sha256']
assert hashlib.sha256(archive.read_bytes()).hexdigest() == receipt['archive_sha256']
restored = Path(os.environ['MALLORY_LEGACY_RESTORE_DIR']) / 'zk11-small-campaign'
expected = {item['path']: item for item in manifest['members']}
actual = {p.relative_to(restored).as_posix(): p for p in restored.rglob('*') if p.is_file()}
assert set(actual) == set(expected)
for name, path in actual.items():
    item = expected[name]
    assert path.stat().st_size == item['bytes']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
print(f"verified {len(actual)} restored files in {restored}")
PY
```

The verified copy remains in the temporary directory. Move it to a desired
location only after confirming that destination does not exist.
