"""Bounded analysis JVM heap profile for the unchanged HBase workload."""

import argparse
import unittest

from record_pilot import analysis_heap_mb, jvm_heap_arg


class AnalysisHeapProfileTest(unittest.TestCase):
    def test_defaults_keep_original_jvm_arguments(self):
        self.assertEqual("-Xmx8g", jvm_heap_arg(8192))
        self.assertEqual("-Xmx4g", jvm_heap_arg(4096))

    def test_larger_scope_can_request_bounded_heap(self):
        self.assertEqual("-Xmx16g", jvm_heap_arg(analysis_heap_mb("16384")))
        self.assertEqual("-Xmx6g", jvm_heap_arg(analysis_heap_mb("6144")))

    def test_invalid_values_rejected_before_jvm_launch(self):
        for value in ("invalid", "0", "1023", "32769"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    analysis_heap_mb(value)


if __name__ == "__main__":
    unittest.main()
