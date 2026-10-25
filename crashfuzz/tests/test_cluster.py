import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crashfuzz import cluster  # noqa: E402
from crashfuzz.__main__ import main  # noqa: E402


class ClusterTest(unittest.TestCase):
    def test_each_node_runs_its_own_shard_detached(self):
        commands = cluster.launch(['node0', 'node1', 'node2'], 'Solr', Path('/bulk/r'),
                                  ['--max-trials', '80'], dry_run=True)
        self.assertEqual(len(commands), 3)
        for index, command in enumerate(commands):
            self.assertTrue(command.startswith(f'node{index}: '))
            self.assertIn(f'--shard-index {index} --shard-count 3', command)
            self.assertIn('--system Solr', command)
            self.assertIn('--max-trials 80', command)
            self.assertIn('setsid nohup', command)
            self.assertIn(f'/bulk/r/logs/worker-Solr-{index}-of-3.log', command)

    def test_cli_rejects_a_shard_outside_its_count(self):
        with self.assertRaises(SystemExit):
            main(['worker', '--system', 'HDFS', '--shard-index', '2', '--shard-count', '2'])


if __name__ == '__main__':
    unittest.main()
