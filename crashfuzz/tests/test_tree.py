import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crashfuzz import settings, tree, worker  # noqa: E402
from crashfuzz.runners import base, tree as tree_runner  # noqa: E402

TEST = 'org.example.TestCausynthThing'


def jar(path, *names):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        for name in names:
            archive.writestr(name, b'\xca\xfe\xba\xbe')
    return path


def pom(module, artifact, version=None, parent='1.0-SNAPSHOT'):
    module.mkdir(parents=True, exist_ok=True)
    own = f'<version>{version}</version>' if version else ''
    (module / 'pom.xml').write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0">'
        f'<parent><version>{parent}</version></parent>'
        f'<artifactId>{artifact}</artifactId>{own}</project>')
    (module / 'target/classes').mkdir(parents=True, exist_ok=True)


class TreeFixture:
    """A built tree: two modules, a Surefire report, GraphChecker on its classpath."""

    def __init__(self, root: Path):
        self.root = root
        self.tree = root / 'tree'
        self.m2 = root / 'm2'
        pom(self.tree / 'common', 'demo-common')
        pom(self.tree / 'server', 'demo-server')
        pom(self.tree / 'extra', 'demo-extra', version='${revision}')
        self.test_classes = self.tree / 'server/target/test-classes'
        test_class = self.test_classes / 'org/example/TestCausynthThing.class'
        test_class.parent.mkdir(parents=True)
        test_class.write_bytes(b'\xca\xfe\xba\xbe Lorg/junit/jupiter/api/Test; ')
        self.common_jar = jar(self.m2 / 'org/demo/demo-common/1.0-SNAPSHOT/'
                                        'demo-common-1.0-SNAPSHOT.jar', 'org/demo/A.class')
        self.common_tests = jar(self.m2 / 'org/demo/demo-common/1.0-SNAPSHOT/'
                                          'demo-common-1.0-SNAPSHOT-tests.jar', 'org/demo/T.class')
        (self.tree / 'common/target/test-classes').mkdir(parents=True)
        self.old_common = jar(self.m2 / 'org/demo/demo-common/0.9/demo-common-0.9.jar',
                              'org/demo/A.class')
        self.extra = jar(self.m2 / 'org/demo/demo-extra/2.0-SNAPSHOT/demo-extra-2.0-SNAPSHOT.jar',
                         'org/demo/E.class')
        self.graphchecker = jar(self.m2 / 'org/example/GraphChecker/1.0-SNAPSHOT/'
                                          'GraphChecker-1.0-SNAPSHOT.jar',
                                'edu/uva/liftlab/graphchecker/runtime/MessageDoors.class')
        self.engine = jar(self.m2 / 'org/junit/platform/junit-platform-engine/1.13.3/'
                                    'junit-platform-engine-1.13.3.jar', 'org/junit/E.class')
        self.launcher = jar(self.m2 / 'org/junit/platform/junit-platform-launcher/1.13.3/'
                                      'junit-platform-launcher-1.13.3.jar', 'org/junit/L.class')
        self.third = jar(self.m2 / 'org/other/lib/3.1/lib-3.1.jar', 'org/other/L.class')
        reports = self.tree / 'server/target/surefire-reports'
        reports.mkdir(parents=True)
        entries = [self.test_classes, self.tree / 'server/target/classes', self.graphchecker,
                   self.common_jar, self.common_tests, self.old_common, self.extra,
                   self.third, self.engine, self.launcher, self.root / 'missing.jar']
        (reports / f'TEST-{TEST}.xml').write_text(
            '<testsuite><properties>'
            f'<property name="java.class.path" value="{":".join(map(str, entries))}"/>'
            f'<property name="basedir" value="{self.tree / "server"}"/>'
            '</properties></testsuite>')

    def row(self):
        return {'case_id': 'OLD-1', 'system': 'HBase', 'cluster_test': TEST + '#check',
                'tree': {'path': str(self.tree),
                         'jvm_properties': ['-Dtest.build.data={data}',
                                            '-Dcache={test_classes}', '-Dflag=true']}}


class TreeWorkloadTest(unittest.TestCase):
    def test_the_report_classpath_without_graphchecker_and_with_the_trees_classes(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = TreeFixture(Path(directory))
            workload = tree.resolve(fixture.row(), TEST, 'check',
                                    ('lib/demo-server-1.0.jar', 'lib/demo-common-1.0.jar'), '2g')
            classpath = workload['classpath']
            self.assertEqual(workload['dropped'], [str(fixture.graphchecker)])
            self.assertNotIn(str(fixture.common_jar), classpath)
            self.assertIn(str(fixture.tree / 'common/target/classes'), classpath)
            self.assertIn(str(fixture.tree / 'common/target/test-classes'), classpath)
            self.assertIn(str(fixture.old_common), classpath)     # another version: not the tree's
            # a module whose version is a property stands for the tree's snapshots only
            self.assertIn(str(fixture.tree / 'extra/target/classes'), classpath)
            self.assertIn(str(fixture.third), classpath)
            self.assertNotIn(str(fixture.root / 'missing.jar'), classpath)
            self.assertEqual(workload['analysis_dirs'],
                             [str(fixture.tree / 'server/target/classes'),
                              str(fixture.tree / 'common/target/classes')])
            self.assertEqual(workload['test_classes'], str(fixture.test_classes))
            self.assertEqual(workload['launcher'], 'jupiter')
            self.assertEqual(workload['heap'], '2g')
            self.assertEqual(tree.analysis(workload, {'max_methods': 400})['process_dirs'],
                             workload['analysis_dirs'])

    def test_a_tree_without_the_release_modules_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = TreeFixture(Path(directory))
            with self.assertRaises(ValueError):
                tree.resolve(fixture.row(), TEST, 'check', ('lib/demo-client-1.0.jar',), '2g')

    def test_release_artifacts_and_ant_class_directories(self):
        self.assertEqual(tree.release_artifacts(('a/hadoop-hdfs-3.4.3.jar', 'zookeeper-3.8.7.jar',
                                                 'x/solr-core-8.11.4.jar')),
                         {'hadoop-hdfs', 'zookeeper', 'solr-core'})
        root = Path('/t')
        self.assertEqual(tree.entry_artifact('/t/solr/build/solr-core/classes/java', root),
                         'solr-core')
        self.assertTrue(tree.is_test_entry('/t/solr/build/solr-core/classes/test'))
        self.assertIsNone(tree.entry_artifact('/elsewhere/lib-1.0.jar', root))

    def test_runner_command_formats_the_rows_properties_and_refuses_graphchecker(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = TreeFixture(Path(directory))
            workload = tree.resolve(fixture.row(), TEST, 'check',
                                    ('lib/demo-server-1.0.jar',), '2g')
            request = base.Request('OLD-1', TEST, 'check', Path(directory) / 'out', None, None,
                                   60)
            scratch = Path(directory) / 'scratch'
            with patch.object(tree_runner, 'compile_runner') as compiled, \
                    patch.object(tree_runner, 'require_agent', return_value=Path('/agent.jar')), \
                    patch.object(settings, 'BUILD', Path(directory) / 'build'):
                argv = tree_runner.command(workload, request, scratch)
                self.assertTrue(compiled.called)
                self.assertIn('-Dtest.build.data=' + str(scratch / 'data'), argv)
                self.assertIn('-Dcache=' + str(fixture.test_classes), argv)
                self.assertIn('-Dflag=true', argv)
                self.assertIn('-Xmx2g', argv)
                self.assertEqual(argv[-3:], ['RunJupiterMethod', TEST, 'check'])
                self.assertNotIn('GraphChecker', argv[argv.index('-cp') + 1])
                adapter = Path(directory) / 'adapter'
                (adapter / 'edu/uva/liftlab/graphchecker/runtime').mkdir(parents=True)
                workload['adapter'] = {'directory': str(adapter)}
                workload['classpath'].append(str(adapter))
                tree_runner.command(workload, request, scratch)     # the stand-ins are no GraphChecker
                workload['classpath'].append(str(fixture.graphchecker))
                with self.assertRaises(ValueError):
                    tree_runner.command(workload, request, scratch)

    def test_worker_reads_a_tree_rows_source_and_skips_type_annotations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'tree/src/Target.java'
            source.parent.mkdir(parents=True)
            source.write_text('package example;\nimport org.demo.KeeperException;\n'
                              'class Target { void check() {\n'
                              'throw new KeeperException.@a.b.Marker("x,y") Moved();\n}}\n')
            row = {'system': 'ZooKeeper', 'tree': {'path': str(root / 'tree')},
                   'check_code': 'throw new KeeperException.@a.b.Marker("x,y") Moved();',
                   'exact_check_location': {'file': 'src/Target.java', 'selected_line': 4}}
            self.assertEqual(worker.exception_type(row), 'org.demo.KeeperException$Moved')
            row['check_code'] = 'throw new @Marker("hdfs-a,"\n+ "hdfs-b") Missing("k");'
            self.assertEqual(worker.exception_type(row), 'example.Missing')

    def test_runner_command_names_the_tree_workload(self):
        spec = worker.system_of('HDFS')
        command = worker.runner_command(spec, 'OLD-1', TEST, 'check', '{trace_dir}',
                                        Path('/s.json'), tree=Path('/w.json'), timeout=99)
        self.assertEqual(command[command.index('--tree') + 1], '/w.json')
        self.assertEqual(command[command.index('--timeout') + 1], '99')


if __name__ == '__main__':
    unittest.main()
