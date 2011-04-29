# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

""" Unit-tests for the Answer Tracker Mail Notifications. """

__metaclass__ = type

from unittest import TestCase

from zope.component import getUtility
from zope.interface import implements
from zope.security.proxy import removeSecurityProxy

from canonical.testing import DatabaseFunctionalLayer
from lp.answers.enums import QuestionRecipientSet
from lp.answers.interfaces.questioncollection import IQuestionSet
from lp.answers.notification import (
    QuestionAddedNotification,
    QuestionModifiedDefaultNotification,
    QuestionModifiedOwnerNotification,
    QuestionNotification,
    QuestionUnsupportedLanguageNotification,
    )
from lp.registry.interfaces.person import IPerson
from lp.services.worlddata.interfaces.language import ILanguageSet
from lp.testing import TestCaseWithFactory


class TestQuestionModifiedNotification(QuestionModifiedDefaultNotification):
    """Subclass that do not send emails and with simpler initialization.

    Since notifications are handlers that accomplish their action on
    initialization, override the relevant method to make them easier to test.
    """

    def initialize(self):
        """Leave the fixture to initialize the notification properly."""
        self.new_message = None

    def shouldNotify(self):
        """Do not send emails!"""
        return False


class StubQuestion:
    """Question with a only an id and title attributes."""

    def __init__(self, id=1, title="Question title"):
        self.id = id
        self.title = title
        self.owner = FakeUser()
        self.messages = []


class StubQuestionMessage:
    """Question message with only a subject attribute."""

    def __init__(self, subject='Message subject'):
        self.subject = subject


class FakeUser:
    """A fake user."""
    implements(IPerson)


class FakeEvent:
    """A fake event."""
    user = FakeUser()
    object_before_modification = StubQuestion()


class QuestionModifiedDefaultNotificationTestCase(TestCase):
    """Test cases for mail notifications about modified questions."""

    def setUp(self):
        """Create a notification with a fake question."""
        self.notification = TestQuestionModifiedNotification(
            StubQuestion(), FakeEvent())

    def test_recipient_set(self):
        self.assertEqual(
            QuestionRecipientSet.SUBSCRIBER,
            self.notification.recipient_set)

    def test_buildBody_with_separator(self):
        # A body with a separator is preserved.
        formatted_body = self.notification.buildBody(
            "body\n-- ", "rationale")
        self.assertEqual(
            "body\n-- \nrationale", formatted_body)

    def test_buildBody_without_separator(self):
        # A separator will added to body if one is not present.
        formatted_body = self.notification.buildBody(
            "body -- mdash", "rationale")
        self.assertEqual(
            "body -- mdash\n-- \nrationale", formatted_body)

    def test_getSubject(self):
        """getSubject() when there is no message added to the question."""
        self.assertEquals(
            'Re: [Question #1]: Question title',
            self.notification.getSubject())

    def test_user_is_event_user(self):
        """The notification user is always the event user."""
        question = StubQuestion()
        event = FakeEvent()
        notification = TestQuestionModifiedNotification(question, event)
        self.assertEqual(event.user, notification.user)
        self.assertNotEqual(question.owner, notification.user)


class TestQuestionModifiedOwnerNotification(
                                           QuestionModifiedOwnerNotification):
    """A subclass that does not send emails."""

    def shouldNotify(self):
        return False


class QuestionModifiedOwnerNotificationTestCase(TestCase):
    """Test cases for mail notifications about owner modified questions."""

    def setUp(self):
        self.question = StubQuestion()
        self.event = FakeEvent()
        self.notification = TestQuestionModifiedOwnerNotification(
            self.question, self.event)

    def test_recipient_set(self):
        self.assertEqual(
            QuestionRecipientSet.ASKER,
            self.notification.recipient_set)


class TestQuestionAddedNotification(QuestionAddedNotification):
    """A subclass that does not send emails."""

    def shouldNotify(self):
        return False


class QuestionAddedNotificationTestCase(TestCase):
    """Test cases for mail notifications about created questions."""

    def setUp(self):
        self.question = StubQuestion()
        self.event = FakeEvent()
        self.notification = TestQuestionAddedNotification(
            self.question, self.event)

    def test_recipient_set(self):
        self.assertEqual(
            QuestionRecipientSet.ASKER_SUBSCRIBER,
            self.notification.recipient_set)

    def test_user_is_question_owner(self):
        """The notification user is always the question owner."""
        self.assertEqual(self.question.owner, self.notification.user)
        self.assertNotEqual(self.event.user, self.notification.user)


class TestQuestionUnsupportedLanguageNotification(
                                     QuestionUnsupportedLanguageNotification):
    """A subclass that does not send emails."""

    def shouldNotify(self):
        return False


class QuestionUnsupportedLanguageNotificationTestCase(TestCase):
    """Test notifications about questions with unsupported languages."""

    def setUp(self):
        self.question = StubQuestion()
        self.event = FakeEvent()
        self.notification = TestQuestionUnsupportedLanguageNotification(
            self.question, self.event)

    def test_recipient_set(self):
        self.assertEqual(
            QuestionRecipientSet.CONTACT,
            self.notification.recipient_set)


class TestQuestionNotification(QuestionNotification):
    """A subclass to exercise question notifcations."""

    recipient_set = QuestionRecipientSet.ASKER_SUBSCRIBER

    def getBody(self):
        return 'body'


class QuestionNotificationTestCase(TestCaseWithFactory):
    """Test common question notification behavior."""

    layer = DatabaseFunctionalLayer

    def makeQuestion(self):
        """Create question that does not trigger a notification."""
        asker = self.factory.makePerson()
        product = self.factory.makeProduct()
        naked_question_set = removeSecurityProxy(getUtility(IQuestionSet))
        question = naked_question_set.new(
            title='title', description='description', owner=asker,
            language=getUtility(ILanguageSet)['en'],
            product=product, distribution=None, sourcepackagename=None)
        return question

    def test_init_enqueue(self):
        # Creating a question notification creates a queation email job.
        question = self.makeQuestion()
        event = FakeEvent()
        event.user = self.factory.makePerson()
        notification = TestQuestionNotification(question, event)
        self.assertEqual(
            notification.recipient_set.name,
            notification.job.metadata['recipient_set'])
        self.assertEqual(notification.question, notification.job.question)
        self.assertEqual(notification.user, notification.job.user)
        self.assertEqual(notification.getSubject(), notification.job.subject)
        self.assertEqual(notification.getBody(), notification.job.body)
        self.assertEqual(notification.getHeaders(), notification.job.headers)
