# Copyright 2005-2007 Canonical Ltd.  All rights reserved.

"""Interfaces for things which have Questions."""

__metaclass__ = type

__all__ = [
    'IAnswersFrontPageSearchForm',
    'IQuestionTarget',
    'IManageAnswerContactsForm',
    'ISearchQuestionsForm',
    'get_supported_languages',
    ]

import sets

from zope.component import getUtility
from zope.interface import Interface
from zope.schema import Bool, Choice, List, Set, TextLine
from zope.schema.interfaces import IContextSourceBinder
from zope.schema.vocabulary import SimpleVocabulary, SimpleTerm

from canonical.launchpad import _
from canonical.launchpad.interfaces.language import ILanguageSet
from canonical.launchpad.interfaces.question import (
    ISearchableByQuestionOwner, QUESTION_STATUS_DEFAULT_SEARCH)
from canonical.lp.dbschema import QuestionSort


def get_supported_languages(question_target):
    """Common implementation for IQuestionTarget.getSupportedLanguages()."""
    assert IQuestionTarget.providedBy(question_target)
    langs = set()
    for contact in question_target.answer_contacts:
        langs |= contact.getSupportedLanguages()
    langs.add(getUtility(ILanguageSet)['en'])
    return langs


class IQuestionTarget(ISearchableByQuestionOwner):
    """An object that can have a new question asked about it."""

    def newQuestion(owner, title, description, language=None,
                    datecreated=None):
        """Create a new question.

         A new question is created with status OPEN.

        The owner and all of the target answer contacts will be subscribed
        to the question.

        :owner: An IPerson.
        :title: A string.
        :description: A string.
        :language: An ILanguage. If that parameter is omitted, the question
                 is assumed to be created in English.
        :datecreated:  A datetime object that will be used for the datecreated
                attribute. Defaults to canonical.database.constants.UTC_NOW.
        """

    def getQuestion(question_id):
        """Return the question by its id, if it is applicable to this target.

        :question_id: A question id.

        If there is no such question number for this target, return None
        """

    def findSimilarQuestions(title):
        """Return questions similar to title.

        Return a list of question similar to the title provided. These
        questions should be found using a fuzzy search. The list should be
        ordered from the most similar question to the least similar question.

        :title: A phrase
        """

    def addAnswerContact(person):
        """Add a new answer contact.

        :person: An IPerson.

        Returns True if the person was added, False if the person already was
        an answer contact.
        """

    def removeAnswerContact(person):
        """Remove an answer contact.

        :person: An IPerson.

        Returns True if the person was removed, False if the person wasn't an
        answer contact.
        """

    def getSupportedLanguages():
        """Return the set of languages spoken by at least one of this object's
        answer contacts.

        An answer contact is considered to speak a given language if that
        language is listed as one of his preferred languages.
        """

    answer_contacts = List(
        title=_("Answer Contacts"),
        description=_(
            "Persons that are willing to provide support for this target. "
            "They receive email notifications about each new question as "
            "well as for changes to any questions related to this target."),
        value_type=Choice(vocabulary="ValidPersonOrTeam"))

    direct_answer_contacts = List(
        title=_("Direct Answer Contacts"),
        description=_(
            "IPersons that registered as answer contacts explicitely on "
            "this target. (answer_contacts may include answer contacts "
            "inherited from other context.)"),
        value_type=Choice(vocabulary="ValidPersonOrTeam"))


# These schemas are only used by browser/questiontarget.py and should really
# live there. See Bug #66950.
class IManageAnswerContactsForm(Interface):
    """Schema for managing answer contacts."""

    want_to_be_answer_contact = Bool(
        title=_("Subscribe me automatically to new question"),
        required=False)
    answer_contact_teams = List(
        title=_("Team answer contacts"),
        value_type=Choice(vocabulary="PersonTeamParticipations"),
        required=False)
        
        
class ISearchQuestionsForm(Interface):
    """Schema for the search question form."""

    search_text = TextLine(title=_('Search text'), required=False)

    sort = Choice(title=_('Sort order'), required=True,
                  vocabulary='QuestionSort',
                  default=QuestionSort.RELEVANCY)
    
    status = Set(title=_('Status'), required=False,
                 value_type=Choice(vocabulary='QuestionStatus'),
                 default=sets.Set(QUESTION_STATUS_DEFAULT_SEARCH))


class IAnswersFrontPageSearchForm(ISearchQuestionsForm):
    """Schema for the Answers front page search form."""

    scope = Choice(title=_('Search scope'), required=False,
                   vocabulary='DistributionOrProductOrProject')
