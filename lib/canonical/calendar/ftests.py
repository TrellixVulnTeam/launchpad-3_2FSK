"""
Functional tests for canonical.calendar

Most of the tests are testing ZCML directives in a very unit-test-like fashion.
They are not unit tests because they need the Zope 3 ZCML machinery to be set
up, so that directives like "adapter" work.
"""

import unittest
from zope.testing import doctest
from canonical.functional import FunctionalTestSetup

__metaclass__ = type


def doctest_adaptation():
    """Test adapter configuration in configure.zcml

    There should be an adapter from IPerson to ICalendar.

        >>> from canonical.launchpad.interfaces.person import IPerson
        >>> from zope.interface import implements
        >>> class FakePerson:
        ...     implements(IPerson)
        >>> person = FakePerson()

        >>> from schoolbell.interfaces import ICalendar
        >>> calendar = ICalendar(person)

        >>> ICalendar.providedBy(calendar)
        True

    There should be an adapter from IPersonApp to ICalendar.

        >>> from canonical.launchpad.interfaces.person import IPersonApp
        >>> class FakePersonApp:
        ...     implements(IPersonApp)
        ...     person = FakePerson()
        >>> personapp = FakePersonApp()

        >>> calendar = ICalendar(personapp)
        >>> ICalendar.providedBy(calendar)
        True

    """


def doctest_views():
    """Test adapter configuration in configure.zcml

    There should be a view for RootObject, named '+calendar'.

        >>> from zope.app import zapi
        >>> from zope.publisher.browser import TestRequest
        >>> from canonical.publication import rootObject
        >>> request = TestRequest()
        >>> root = rootObject
        >>> view = zapi.getView(root, '+calendar', request)
        >>> from canonical.calendar import UsersCalendarTraverser
        >>> isinstance(view, UsersCalendarTraverser)
        True

    There should be a view for IPersonApp, named '+calendar'.

        >>> from zope.interface import implements
        >>> from canonical.launchpad.interfaces.person import IPersonApp
        >>> class FakePersonApp:
        ...     implements(IPersonApp)
        >>> context = FakePersonApp()
        >>> view = zapi.getView(context, '+calendar', request)
        >>> from canonical.calendar import CalendarAdapterTraverser
        >>> isinstance(view, CalendarAdapterTraverser)
        True

    The default view for ICalendar should be '+index'.

        >>> from canonical.calendar import ICalendar
        >>> class FakeCalendar:
        ...     implements(ICalendar)
        >>> context = FakeCalendar()
        >>> zapi.getDefaultViewName(context, request)
        u'+index'

        >>> view = zapi.getView(context, '+index', request)

    """


def setUp(doctest):
    FunctionalTestSetup().setUp()


def tearDown(doctest):
    FunctionalTestSetup().tearDown()


def test_suite():
    return unittest.TestSuite([
                doctest.DocTestSuite(setUp=setUp,
                                     tearDown=tearDown)
                ])

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
