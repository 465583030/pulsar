import sys

import pulsar
from pulsar.utils.log import lazyproperty
from pulsar.utils.config import section_docs, TestOption

from .populate import populate, random_string
from .result import Plugin, TestStream, TestRunner, TestResult
from .plugins.base import WrapTest, TestPlugin, validate_plugin_list
from .loader import TestLoader
from .utils import (sequential, ActorTestMixin, AsyncAssert, check_server,
                    test_timeout, dont_run_with_thread, TestFailure)
from .wsgi import HttpTestClient
from .runner import Runner


__all__ = ['populate',
           'random_string',
           'HttpTestClient',
           'TestLoader',
           'Plugin',
           'TestStream',
           'TestRunner',
           'TestResult',
           'WrapTest',
           'TestPlugin',
           'sequential',
           'ActorTestMixin',
           'AsyncAssert',
           'TestFailure',
           'check_server',
           'test_timeout',
           'dont_run_with_thread']


pyver = '%s.%s' % (sys.version_info[:2])

section_docs['Test'] = '''
This section covers configuration parameters used by the
:ref:`Asynchronous/Parallel test suite <apps-test>`.'''


class TestVerbosity(TestOption):
    name = 'verbosity'
    flags = ['--verbosity']
    validator = pulsar.validate_pos_int
    type = int
    default = 1
    desc = """Test verbosity, 0, 1, 2, 3"""


class TestTimeout(TestOption):
    flags = ['--test-timeout']
    validator = pulsar.validate_pos_int
    type = int
    default = 20
    desc = '''\
        Tests which take longer than this many seconds are timed-out
        and failed.'''


class TestLabels(TestOption):
    name = "labels"
    nargs = '*'
    validator = pulsar.validate_list
    desc = """\
        Optional test labels to run.

        If not provided all tests are run.
        To see available labels use the ``-l`` option."""


class TestExcludeLabels(TestOption):
    name = "exclude_labels"
    flags = ['-e', '--exclude-labels']
    nargs = '+'
    desc = 'Exclude a group o labels from running.'
    validator = pulsar.validate_list


class TestSize(TestOption):
    name = 'size'
    flags = ['--size']
    choices = ('tiny', 'small', 'normal', 'big', 'huge')
    default = 'normal'
    desc = """Optional test size."""


class TestList(TestOption):
    name = "list_labels"
    flags = ['-l', '--list-labels']
    action = 'store_true'
    default = False
    validator = pulsar.validate_bool
    desc = """List all test labels without performing tests."""


class TestSequential(TestOption):
    name = "sequential"
    flags = ['--sequential']
    action = 'store_true'
    default = False
    validator = pulsar.validate_bool
    desc = """Run test functions sequentially."""


class Coveralls(TestOption):
    flags = ['--coveralls']
    action = 'store_true'
    default = False
    validator = pulsar.validate_bool
    desc = """Publish coverage to coveralls."""


class TestPlugins(TestOption):
    flags = ['--test-plugins']
    validator = validate_plugin_list
    nargs = '+'
    default = ['pulsar.apps.test.plugins.bench:BenchMark',
               'pulsar.apps.test.plugins.profile:Profile']
    desc = '''Test plugins.'''


class TestModules(TestOption):
    flags = ['--test-modules']
    validator = pulsar.validate_list
    nargs = '+'
    default = []
    desc = '''\
        An iterable over modules where to look for tests.
        '''


class TestSuite(pulsar.Application):
    '''An asynchronous test suite which works like a task queue.

    Each task is a group of test methods in a python TestCase class.

    :parameter modules: An iterable over modules where to look for tests.
        If not provided it is set as default to ``["tests"]`` which loads all
        python module from the tests module in a recursive fashion.
        Check the the :class:`.TestLoader` for detailed information.
    :parameter plugins: Optional list of dotted path to
        :class:`.TestPlugin` classes.
    '''
    name = 'test'
    cfg = pulsar.Config(
        description='pulsar test suite',
        apps=['test'],
        log_level=['none']
    )

    @lazyproperty
    def loader(self):
        """Instance of the :class:`.TestLoader` used for loading test cases
        """
        return TestLoader(self)

    def on_config(self, arbiter):
        loader = self.loader
        stream = loader.stream
        if loader.abort_message:
            stream.writeln(str(loader.abort_message))
            return False

        stream.writeln(sys.version)
        if self.cfg.list_labels:    # pragma    nocover
            tags = self.cfg.labels
            if tags:
                s = '' if len(tags) == 1 else 's'
                stream.writeln('\nTest labels for%s %s:' %
                               (s, ', '.join(tags)))
            else:
                stream.writeln('\nAll test labels:')
            stream.writeln('')
            for tag in loader.tags(tags, self.cfg.exclude_labels):
                stream.writeln(tag)
            stream.writeln('')
            return False

        elif self.cfg.coveralls:    # pragma nocover
            from pulsar.apps.test.cov import coveralls
            coveralls()
            return False

    def monitor_start(self, monitor):
        '''When the monitor starts load all test classes into the queue'''
        self.cfg.set('workers', 0)

        if self.cfg.callable:
            self.cfg.callable()

        monitor._loop.call_soon(Runner, monitor, self)

    @classmethod
    def create_config(cls, *args, **kwargs):
        cfg = super().create_config(*args, **kwargs)
        for plugin in cfg.test_plugins:
            cfg.settings.update(plugin.config.settings)
        return cfg

    def arbiter_params(self):
        params = super().arbiter_params()
        params['concurrency'] = self.cfg.concurrency
        return params
