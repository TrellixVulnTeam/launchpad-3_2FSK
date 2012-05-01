# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Support code for using a custom test result in test.py."""

__metaclass__ = type
__all__ = [
    'filter_tests',
    'patch_find_tests',
    ]

from unittest import TestSuite

from zope.testing.testrunner import find


def patch_find_tests(hook):
    """Add a post-processing hook to zope.testing.testrunner.find_tests.

    This is useful for things like filtering tests or listing tests.

    :param hook: A callable that takes the output of the real
        `testrunner.find_tests` and returns a thing with the same type and
        structure.
    """
    real_find_tests = find.find_tests

    def find_tests(*args):
        return hook(real_find_tests(*args))

    find.find_tests = find_tests


def filter_tests(list_name):
    """Create a hook for `patch_find_tests` that filters tests based on id.

    :param list_name: A filename that contains a newline-separated list of
        test ids, as generated by `list_tests`.
    :return: A callable that takes a result of `testrunner.find_tests` and
        returns only those tests with ids in the file 'list_name'.
    """
    def do_filter(tests_by_layer_name):
        # Read the tests, filtering out any blank lines.
        tests = filter(None, [line.strip() for line in open(list_name, 'rb')])
        suites_by_layer = {}
        for layer_name, suite in tests_by_layer_name.iteritems():
            testnames = {}
            for t in suite:
                testnames[t.id()] = t
            suites_by_layer[layer_name] = testnames

        def find_layer(t):
            # There are ~30 layers.
            for layer, names in suites_by_layer.items():
                if t in names:
                    return layer, names[t]
            return None, None

        ordered_layers = []
        result = {}
        for testname in tests:
            layer, test = find_layer(testname)
            if not layer:
                raise Exception("Test not found: %s" % testname)
            if not layer in ordered_layers:
                ordered_layers.append(layer)
            suite = result.setdefault(layer, TestSuite())
            suite.addTest(test)
        return result
    return do_filter
