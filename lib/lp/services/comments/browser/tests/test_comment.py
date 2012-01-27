from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.services.comments.browser.comment import CommentBodyDownloadView
from lp.services.webapp.servers import LaunchpadTestRequest


class FakeComment:
    """Fake to avoid depending on a particular implementation."""

    def __init__(self, body_text):
        self.body_text = body_text
        self.index = 5


class TestCommentBodyDownloadView(TestCaseWithFactory):
    """Test the CommentBodyDownloadView."""

    layer = DatabaseFunctionalLayer

    def view(self, body):
        comment = FakeComment(body)
        request = LaunchpadTestRequest()
        view = CommentBodyDownloadView(comment, request)
        return view()

    def test_anonymous_body_obfuscated(self):
        """For anonymous users, email addresses are obfuscated."""
        output = self.view()
        self.assertNotIn(output, 'example@example.org')
        self.assertIn(output, '<email address hidden>')

    def test_logged_in_not_obfuscated(self):
        """For logged-in users, email addresses are not obfuscated."""
        with person_logged_in(self.factory.makePerson()):
            output = self.view('example@example.org')
            self.assertIn(output, 'example@example.org')
            self.assertNotIn(output, '<email address hidden>')
