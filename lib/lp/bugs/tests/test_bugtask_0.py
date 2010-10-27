# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for bugtask.py."""

__metaclass__ = type

from doctest import (
    DocTestSuite,
    ELLIPSIS,
    NORMALIZE_WHITESPACE,
    REPORT_NDIFF,
    )


def test_open_and_resolved_statuses(self):
    """
    There are constants that are used to define which statuses are for
    resolved bugs (RESOLVED_BUGTASK_STATUSES), and which are for
    unresolved bugs (UNRESOLVED_BUGTASK_STATUSES). The two constants
    include all statuses defined in BugTaskStatus, except for Unknown.

        >>> from lp.bugs.interfaces.bugtask import (
        ...     BugTaskStatus, RESOLVED_BUGTASK_STATUSES,
        ...     UNRESOLVED_BUGTASK_STATUSES)
        >>> not_included_status = set(BugTaskStatus.items).difference(
        ...     RESOLVED_BUGTASK_STATUSES + UNRESOLVED_BUGTASK_STATUSES)
        >>> [status.name for status in not_included_status]
        ['UNKNOWN']
    """


def test_suite():
    suite = DocTestSuite(
        optionflags=REPORT_NDIFF|NORMALIZE_WHITESPACE|ELLIPSIS)
    return suite
