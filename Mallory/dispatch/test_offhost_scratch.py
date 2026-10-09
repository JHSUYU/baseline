from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from .offhost_scratch import restore_members


class OffhostScratchTest(unittest.TestCase):
    def test_restore_exact_bytes_and_reject_tampered_local_file(self):
        name = "trials/r0001/scratch/node/log.1"
        content = b"\x00scratch evidence\xff" * 100
        expected = {name: {"sha256": hashlib.sha256(content).hexdigest(),
                           "bytes": len(content)}}
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as packed:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            packed.addfile(member, io.BytesIO(content))
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary)
            self.assertEqual(1, restore_members(
                campaign, io.BytesIO(buffer.getvalue()), expected))
            self.assertEqual(content, (campaign / name).read_bytes())
            self.assertEqual(0, restore_members(
                campaign, io.BytesIO(buffer.getvalue()), expected))
            (campaign / name).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "existing scratch differs"):
                restore_members(campaign, io.BytesIO(buffer.getvalue()), expected)

    def test_restore_rejects_archive_member_with_wrong_hash(self):
        name = "trials/r0001/scratch/node/log.1"
        content = b"actual"
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as packed:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            packed.addfile(member, io.BytesIO(content))
        expected = {name: {"sha256": hashlib.sha256(b"expected").hexdigest(),
                           "bytes": len(content)}}
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "restored scratch differs"):
                restore_members(Path(temporary), io.BytesIO(buffer.getvalue()), expected)
            self.assertFalse((Path(temporary) / name).exists())


if __name__ == "__main__":
    unittest.main()
