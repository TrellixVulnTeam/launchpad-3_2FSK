# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for CodeReviewComments."""

__metaclass__ = type

from testtools.matchers import Not
from soupmatchers import (
    HTMLContains,
    Tag,
    )

from lp.code.browser.codereviewcomment import (
    CodeReviewDisplayComment,
    ICodeReviewDisplayComment,
    )
from lp.services.webapp import canonical_url
from lp.services.webapp.interfaces import IPrimaryContext
from lp.services.webapp.testing import verifyObject
from lp.testing import (
    BrowserTestCase,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


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


class TestCodeReviewCommentHtml(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def test_comment_page_has_meta_description(self):
        # The CodeReviewDisplayComment class provides IComment.
        with person_logged_in(self.factory.makePerson()):
            comment = self.factory.makeCodeReviewComment()

        display_comment = CodeReviewDisplayComment(comment)
        browser = self.getViewBrowser(display_comment)
        self.assertThat(
            browser.contents,
            HTMLContains(Tag(
                'meta description', 'meta',
                dict(
                    name='description',
                    content=comment.message_body))))

    def test_long_comments_not_truncated(self):
        """Long comments displayed by themselves are not truncated."""
        comment = self.factory.makeCodeReviewComment(body='x y' * 2000)
        browser = self.getViewBrowser(comment)
        body = Tag('Body text', 'p', text='x y' * 2000)
        self.assertThat(browser.contents, HTMLContains(body))

    def test_excessive_comments_download_link(self):
        """Excessive comments have a download link displayed."""
        comment = self.factory.makeCodeReviewComment(body='x ' * 5001)
        download_url = canonical_url(comment, view_name='+download')
        browser = self.getViewBrowser(comment)
        body = Tag(
            'Download', 'a', {'href': download_url},
            text='Download full text')
        self.assertThat(browser.contents, HTMLContains(body))

    def test_excessive_comments_no_read_more(self):
        """Excessive comments have no "Read more" link."""
        comment = self.factory.makeCodeReviewComment(body='x ' * 5001)
        url = canonical_url(comment, force_local_path=True)
        browser = self.getViewBrowser(comment)
        read_more = Tag(
            'Read more link', 'a', {'href': url}, text='Read more...')
        self.assertThat(browser.contents, Not(HTMLContains(read_more)))

    def test_short_comment_no_download_link(self):
        """Long comments displayed by themselves are not truncated."""
        comment = self.factory.makeCodeReviewComment(body='x ' * 5000)
        download_url = canonical_url(comment, view_name='+download')
        browser = self.getViewBrowser(comment)
        body = Tag(
            'Download', 'a', {'href': download_url},
            text='Download full text')
        self.assertThat(browser.contents, Not(HTMLContains(body)))

    def test_download_view(self):
        comment = self.factory.makeCodeReviewComment()
        browser = self.getViewBrowser(comment, view_name='+download')
        content = comment.message_body
        self.assertEqual(content, browser.contents)
        self.assertEqual(
            'text/plain;charset=utf-8', browser.headers['Content-type'])
        self.assertEqual(
            '%d' % len(content), browser.headers['Content-length'])
        disposition = 'attachment; filename="comment-%d.txt"' % comment.id
        self.assertEqual(disposition, browser.headers['Content-disposition'])
