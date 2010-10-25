# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the question module."""

__metaclass__ = type

__all__ = []

from canonical.testing.layers import DatabaseFunctionalLayer
from lp.answers.publisher import AnswersLayer
from lp.testing import (
    login_person,
    TestCaseWithFactory,
    )
from lp.testing.views import create_initialized_view


class TestQuestionAddView(TestCaseWithFactory):
    """Verify the behavior of the QuestionAddView."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestQuestionAddView, self).setUp()
        self.question_target = self.factory.makeProduct()
        self.user = self.factory.makePerson()
        login_person(self.user)

    def getSearchForm(self, title, language='en'):
        return {
            'field.title': title,
            'field.language': language,
            'field.actions.continue': 'Continue',
            }

    def test_question_title_within_max_display_width(self):
        # Titles (summary in the view) less than 250 characters are accepted.
        form = self.getSearchForm('123456789 ' * 10)
        view = create_initialized_view(
            self.question_target, name='+addquestion', layer=AnswersLayer,
            form=form, principal=self.user)
        self.assertEqual([], view.errors)

    def test_question_title_exceeds_max_display_width(self):
        # Titles (summary in the view) cannot exceed 250 characters.
        form = self.getSearchForm('123456789 ' * 26)
        view = create_initialized_view(
            self.question_target, name='+addquestion', layer=AnswersLayer,
            form=form, principal=self.user)
        self.assertEqual(1, len(view.errors))
        self.assertEqual(
            'The summary cannot exceed 250 characters.', view.errors[0])
