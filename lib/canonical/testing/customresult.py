# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Support code for using a custom test result in test.py."""

__metaclass__ = type
__all__ = [
    'patch_zope_testresult',
    ]

from unittest import TestResult


# XXX: JonathanLange 2009-03-09: Copied and hacked from testtools.
class MultiTestResult(TestResult):
    """A test result that dispatches to many test results."""

    def __init__(self, *results):
        TestResult.__init__(self)
        self._results = list(results)

    def _dispatch(self, message, *args, **kwargs):
        for result in self._results:
            getattr(result, message)(*args, **kwargs)

    def startTest(self, test):
        self._dispatch('startTest', test)

    def stopTest(self, test):
        self._dispatch('stopTest', test)

    def addError(self, test, error):
        self._dispatch('addError', test, error)

    def addFailure(self, test, failure):
        self._dispatch('addFailure', test, failure)

    def addSuccess(self, test):
        self._dispatch('addSuccess', test)


def patch_zope_testresult(result):
    from zope.testing import testrunner
    old_zope_factory = testrunner.TestResult
    def zope_result_factory(options, tests, layer_name=None):
        zope_result = old_zope_factory(options, tests, layer_name=layer_name)
        return MultiTestResult(result, zope_result)
    testrunner.TestResult = zope_result_factory
