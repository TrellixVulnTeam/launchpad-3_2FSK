# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for CodeReviewComments."""

from __future__ import with_statement

__metaclass__ = type

import unittest

from canonical.launchpad.webapp.interfaces import IPrimaryContext
from canonical.launchpad.webapp.testing import verifyObject
from canonical.testing.layers import DatabaseFunctionalLayer
from lp.code.browser.codereviewcomment import (
    CodeReviewDisplayComment,
    ICodeReviewDisplayComment,
    )
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )


class TestCodeReviewComments(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def testPrimaryContext(self):
        # Tests the adaptation of a code review comment into a primary
        # context.
        # We need a person to make a comment.
        with person_logged_in(self.factory.makePerson()):
            # The primary context of a code review comment is the same
            # as the primary context for the branch merge proposal that
            # the comment is for.
            comment = self.factory.makeCodeReviewComment()

        self.assertEqual(
            IPrimaryContext(comment).context,
            IPrimaryContext(comment.branch_merge_proposal).context)

    def test_display_comment_provides_icodereviewdisplaycomment(self):
        # The CodeReviewDisplayComment class provides IComment.
        with person_logged_in(self.factory.makePerson()):
            comment = self.factory.makeCodeReviewComment()

        display_comment = CodeReviewDisplayComment(comment)

        verifyObject(ICodeReviewDisplayComment, display_comment)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
