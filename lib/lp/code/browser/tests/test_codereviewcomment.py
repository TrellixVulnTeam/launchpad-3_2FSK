# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for CodeReviewComments."""

__metaclass__ = type

from soupmatchers import (
    HTMLContains,
    Tag,
    )
from testtools.matchers import (
    Equals,
    Not,
    )
from zope.component import getUtility

from lp.code.browser.codereviewcomment import (
    CodeReviewDisplayComment,
    ICodeReviewDisplayComment,
    )
from lp.code.interfaces.codereviewinlinecomment import (
    ICodeReviewInlineCommentSet,
    )
from lp.services.webapp import canonical_url
from lp.services.webapp.interfaces import IPrimaryContext
from lp.testing import (
    BrowserTestCase,
    person_logged_in,
    StormStatementRecorder,
    TestCaseWithFactory,
    verifyObject,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.testing.matchers import HasQueryCount


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


class TestCodeReviewCommentInlineComments(TestCaseWithFactory):
    """Test `CodeReviewDisplayComment` integration with inline-comments."""

    layer = LaunchpadFunctionalLayer

    def makeInlineComment(self, person, comment, previewdiff=None,
                          comments=None):
        # Test helper for creating inline comments.
        if previewdiff is None:
            previewdiff = self.factory.makePreviewDiff()
        if comments is None:
            comments = {'1': 'Foo'}
        getUtility(ICodeReviewInlineCommentSet).ensureDraft(
            previewdiff, person, comments)
        cric = getUtility(ICodeReviewInlineCommentSet).publishDraft(
            previewdiff, person, comment)
        return cric

    def test_display_comment_inline_comment(self):
        # The CodeReviewDisplayComment links to related inline comments
        # when they exist.
        person = self.factory.makePerson()
        with person_logged_in(person):
            comment = self.factory.makeCodeReviewComment()
        # `CodeReviewDisplayComment.previewdiff_id` is None if there
        # is no related inline-comments.
        display_comment = CodeReviewDisplayComment(comment)
        self.assertIsNone(display_comment.previewdiff_id)
        # Create a `PreviewDiff` and add inline-comments in
        # the context of this review comment.
        with person_logged_in(person):
            previewdiff = self.factory.makePreviewDiff()
            self.makeInlineComment(person, comment, previewdiff)
        # 'previewdiff_id' property is cached, so its value did not
        # change on the existing object.
        self.assertIsNone(display_comment.previewdiff_id)
        # On a new object, it successfully returns the `PreviewDiff.id`
        # containing inline-comments related with this review comment.
        display_comment = CodeReviewDisplayComment(comment)
        self.assertEqual(previewdiff.id, display_comment.previewdiff_id)

    def test_conversation_with_previewdiffs_populated(self):
        # `CodeReviewConversation` comments have 'previewdiff_id'
        # property pre-populated in view.
        person = self.factory.makePerson()
        merge_proposal = self.factory.makeBranchMergeProposal()
        with person_logged_in(person):
            for i in range(5):
                comment = self.factory.makeCodeReviewComment(
                    merge_proposal=merge_proposal)
                self.makeInlineComment(person, comment)
        from lp.testing.views import create_initialized_view
        view = create_initialized_view(merge_proposal, '+index')
        conversation = view.conversation
        with StormStatementRecorder() as recorder:
            [c.previewdiff_id for c in conversation.comments]
        self.assertThat(recorder, HasQueryCount(Equals(0)))


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

    def test_excessive_comments_redirect_to_download(self):
        """View for excessive comments redirects to download page."""
        comment = self.factory.makeCodeReviewComment(body='x ' * 5001)
        view_url = canonical_url(comment)
        download_url = canonical_url(comment, view_name='+download')
        browser = self.getUserBrowser(view_url)
        self.assertNotEqual(view_url, browser.url)
        self.assertEqual(download_url, browser.url)
        self.assertEqual('x ' * 5001, browser.contents)

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
        """The download view has the expected contents and header."""
        comment = self.factory.makeCodeReviewComment(body=u'\u1234')
        browser = self.getViewBrowser(comment, view_name='+download')
        contents = u'\u1234'.encode('utf-8')
        self.assertEqual(contents, browser.contents)
        self.assertEqual(
            'text/plain;charset=utf-8', browser.headers['Content-type'])
        self.assertEqual(
            '%d' % len(contents), browser.headers['Content-length'])
        disposition = 'attachment; filename="comment-%d.txt"' % comment.id
        self.assertEqual(disposition, browser.headers['Content-disposition'])
