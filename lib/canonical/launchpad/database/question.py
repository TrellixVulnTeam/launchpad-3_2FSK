# Copyright 2004-2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

"""Question models."""

__metaclass__ = type
__all__ = [
    'SimilarQuestionsSearch',
    'Question',
    'QuestionTargetSearch',
    'QuestionPersonSearch',
    'QuestionSet',
    'QuestionTargetMixin',
    ]

from datetime import datetime
import operator
import pytz

from email.Utils import make_msgid

from zope.component import getUtility
from zope.event import notify
from zope.interface import implements, providedBy
from zope.security.proxy import isinstance as zope_isinstance

from sqlobject import (
    ForeignKey, StringCol, SQLMultipleJoin, SQLRelatedJoin, SQLObjectNotFound)
from sqlobject.sqlbuilder import SQLConstant
from storm.store import Store

from canonical.launchpad.interfaces import (
    BugTaskStatus, IBugLinkTarget, IDistribution, IDistributionSet,
    IDistributionSourcePackage, IFAQ, InvalidQuestionStateError, ILanguage,
    ILaunchpadCelebrities, IMessage, IPerson, IProduct, IProductSet,
    IQuestion, IQuestionSet, IQuestionTarget, ISourcePackage,
    QUESTION_STATUS_DEFAULT_SEARCH, QuestionAction, QuestionParticipation,
    QuestionPriority, QuestionSort, QuestionStatus)
from canonical.launchpad.interfaces.sourcepackagename import (
    ISourcePackageNameSet)
from canonical.launchpad.validators.person import validate_public_person

from canonical.database.sqlbase import cursor, quote, SQLBase, sqlvalues
from canonical.database.constants import DEFAULT, UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.nl_search import nl_phrase_search
from canonical.database.enumcol import EnumCol

from canonical.launchpad.database.answercontact import AnswerContact
from canonical.launchpad.database.buglinktarget import BugLinkTargetMixin
from canonical.launchpad.database.language import Language
from canonical.launchpad.database.message import Message, MessageChunk
from canonical.launchpad.database.questionbug import QuestionBug
from canonical.launchpad.database.questionmessage import QuestionMessage
from canonical.launchpad.database.questionsubscription import (
    QuestionSubscription)
from canonical.launchpad.event import (
    SQLObjectCreatedEvent, SQLObjectModifiedEvent)
from canonical.launchpad.helpers import is_english_variant
from canonical.launchpad.mailnotification import (
    NotificationRecipientSet)
from canonical.launchpad.webapp.snapshot import Snapshot
from canonical.lazr import DBItem, Item


class notify_question_modified:
    """Decorator that sends a SQLObjectModifiedEvent after a workflow action.

    This decorator will take a snapshot of the object before the call to
    the decorated workflow_method. It will fire an
    SQLObjectModifiedEvent after the method returns.

    The list of edited_fields will be computed by comparing the snapshot
    with the modified question. The fields that are checked for
    modifications are: status, messages, date_solved, answerer, answer,
    datelastquery and datelastresponse.

    The user triggering the event is taken from the returned message.
    """

    def __call__(self, func):
        """Return the SQLObjectModifiedEvent decorator."""
        def notify_question_modified(self, *args, **kwargs):
            """Create the SQLObjectModifiedEvent decorator."""
            old_question = Snapshot(self, providing=providedBy(self))
            msg = func(self, *args, **kwargs)

            edited_fields = ['messages']
            for field in ['status', 'date_solved', 'answerer', 'answer',
                          'datelastquery', 'datelastresponse', 'target']:
                if getattr(self, field) != getattr(old_question, field):
                    edited_fields.append(field)

            notify(SQLObjectModifiedEvent(
                self, object_before_modification=old_question,
                edited_fields=edited_fields, user=msg.owner))
            return msg
        return notify_question_modified


class Question(SQLBase, BugLinkTargetMixin):
    """See `IQuestion`."""

    implements(IQuestion, IBugLinkTarget)

    _table = 'Question'
    _defaultOrder = ['-priority', 'datecreated']

    # db field names
    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    title = StringCol(notNull=True)
    description = StringCol(notNull=True)
    language = ForeignKey(
        dbName='language', notNull=True, foreignKey='Language')
    status = EnumCol(
        schema=QuestionStatus, notNull=True, default=QuestionStatus.OPEN)
    priority = EnumCol(
        schema=QuestionPriority, notNull=True,
        default=QuestionPriority.NORMAL)
    assignee = ForeignKey(
        dbName='assignee', notNull=False, foreignKey='Person',
        storm_validator=validate_public_person, default=None)
    answerer = ForeignKey(
        dbName='answerer', notNull=False, foreignKey='Person',
        storm_validator=validate_public_person, default=None)
    answer = ForeignKey(dbName='answer', notNull=False,
        foreignKey='QuestionMessage', default=None)
    datecreated = UtcDateTimeCol(notNull=True, default=DEFAULT)
    datedue = UtcDateTimeCol(notNull=False, default=None)
    datelastquery = UtcDateTimeCol(notNull=True, default=DEFAULT)
    datelastresponse = UtcDateTimeCol(notNull=False, default=None)
    date_solved = UtcDateTimeCol(notNull=False, default=None)
    product = ForeignKey(
        dbName='product', foreignKey='Product', notNull=False, default=None)
    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution', notNull=False,
        default=None)
    sourcepackagename = ForeignKey(
        dbName='sourcepackagename', foreignKey='SourcePackageName',
        notNull=False, default=None)
    whiteboard = StringCol(notNull=False, default=None)

    faq = ForeignKey(
        dbName='faq', foreignKey='FAQ', notNull=False, default=None)

    # useful joins
    subscriptions = SQLMultipleJoin('QuestionSubscription',
        joinColumn='question', orderBy='id')
    subscribers = SQLRelatedJoin('Person',
        joinColumn='question', otherColumn='person',
        intermediateTable='QuestionSubscription', orderBy='name')
    bug_links = SQLMultipleJoin('QuestionBug',
        joinColumn='question', orderBy='id')
    bugs = SQLRelatedJoin('Bug', joinColumn='question', otherColumn='bug',
        intermediateTable='QuestionBug', orderBy='id')
    messages = SQLMultipleJoin('QuestionMessage', joinColumn='question',
        prejoins=['message'], orderBy=['QuestionMessage.id'])
    reopenings = SQLMultipleJoin('QuestionReopening', orderBy='datecreated',
        joinColumn='question')

    # attributes
    def target(self):
        """See `IQuestion`."""
        if self.product:
            return self.product
        elif self.sourcepackagename:
            return self.distribution.getSourcePackage(
                self.sourcepackagename.name)
        else:
            return self.distribution

    def _settarget(self, question_target):
        """See Question.target."""
        assert IQuestionTarget.providedBy(question_target), (
            "The target must be an IQuestionTarget")
        if IProduct.providedBy(question_target):
            self.product = question_target
            self.distribution = None
            self.sourcepackagename = None
        # XXX sinzui 2007-04-20 bug=108240
        # We test for ISourcePackage because it is a valid QuestionTarget even
        # though it should not be. SourcePackages are never passed to this
        # mutator.
        elif (ISourcePackage.providedBy(question_target) or
                IDistributionSourcePackage.providedBy(question_target)):
            self.product = None
            self.distribution = question_target.distribution
            self.sourcepackagename = question_target.sourcepackagename
        elif IDistribution.providedBy(question_target):
            self.product = None
            self.distribution = question_target
            self.sourcepackagename = None
        else:
            raise AssertionError("Unknown IQuestionTarget type of %s" %
                question_target)

    target = property(target, _settarget, doc=target.__doc__)

    @property
    def followup_subject(self):
        """See `IMessageTarget`."""
        if not self.messages:
            return 'Re: '+ self.title
        subject = self.messages[-1].title
        if subject[:4].lower() == 're: ':
            return subject
        return 'Re: ' + subject

    def isSubscribed(self, person):
        """See `IQuestion`."""
        return bool(
            QuestionSubscription.selectOneBy(question=self, person=person))

    # Workflow methods

    # The lifecycle of a question is documented in
    # https://help.launchpad.net/QuestionLifeCycle, so remember
    # to update that document for any pertinent changes.
    @notify_question_modified()
    def setStatus(self, user, new_status, comment, datecreated=None):
        """See `IQuestion`."""
        if new_status == self.status:
            raise InvalidQuestionStateError(
                "New status is same as the old one.")

        # If the previous state recorded an answer, clear those
        # information as well.
        self.answerer = None
        self.answer = None
        self.date_solved = None

        return self._newMessage(
            user, comment, datecreated=datecreated,
            action=QuestionAction.SETSTATUS, new_status=new_status)

    @notify_question_modified()
    def addComment(self, user, comment, datecreated=None):
        """See `IQuestion`."""
        return self._newMessage(
            user, comment, datecreated=datecreated,
            action=QuestionAction.COMMENT, new_status=self.status,
            update_question_dates=False)

    @property
    def can_request_info(self):
        """See `IQuestion`."""
        return self.status in [
            QuestionStatus.OPEN, QuestionStatus.NEEDSINFO,
            QuestionStatus.ANSWERED]

    @notify_question_modified()
    def requestInfo(self, user, question, datecreated=None):
        """See `IQuestion`."""
        assert user != self.owner, "Owner cannot use requestInfo()."
        if not self.can_request_info:
            raise InvalidQuestionStateError(
            "Question status != OPEN, NEEDSINFO, or ANSWERED")
        if self.status == QuestionStatus.ANSWERED:
            new_status = self.status
        else:
            new_status = QuestionStatus.NEEDSINFO
        return self._newMessage(
            user, question, datecreated=datecreated,
            action=QuestionAction.REQUESTINFO, new_status=new_status)

    @property
    def can_give_info(self):
        """See `IQuestion`."""
        return self.status in [QuestionStatus.OPEN, QuestionStatus.NEEDSINFO]

    @notify_question_modified()
    def giveInfo(self, reply, datecreated=None):
        """See `IQuestion`."""
        if not self.can_give_info:
            raise InvalidQuestionStateError(
                "Question status != OPEN or NEEDSINFO")
        return self._newMessage(
            self.owner, reply, datecreated=datecreated,
            action=QuestionAction.GIVEINFO, new_status=QuestionStatus.OPEN)

    @property
    def can_give_answer(self):
        """See `IQuestion`."""
        return self.status in [
            QuestionStatus.OPEN, QuestionStatus.NEEDSINFO,
            QuestionStatus.ANSWERED]

    @notify_question_modified()
    def giveAnswer(self, user, answer, datecreated=None):
        """See IQuestion."""
        return self._giveAnswer(user, answer, datecreated)

    def _giveAnswer(self, user, answer, datecreated):
        """Implementation of _giveAnswer that doesn't trigger notifications.
        """
        if not self.can_give_answer:
            raise InvalidQuestionStateError(
            "Question status != OPEN, NEEDSINFO or ANSWERED")
        if self.owner == user:
            new_status = QuestionStatus.SOLVED
            action = QuestionAction.CONFIRM
        else:
            new_status = QuestionStatus.ANSWERED
            action = QuestionAction.ANSWER

        msg = self._newMessage(
            user, answer, datecreated=datecreated, action=action,
            new_status=new_status)

        if self.owner == user:
            self.date_solved = msg.datecreated
            self.answerer = user

        return msg

    @notify_question_modified()
    def linkFAQ(self, user, faq, comment, datecreated=None):
        """See `IQuestion`."""
        if faq is not None:
            assert IFAQ.providedBy(faq), (
                "faq parameter must provide IFAQ or be None")
        assert self.faq != faq, (
            'cannot call linkFAQ() with already linked FAQ')
        self.faq = faq
        if self.can_give_answer:
            return self._giveAnswer(user, comment, datecreated)
        else:
            # The question's status is Solved or Invalid.
            return self.addComment(user, comment, datecreated)

    @property
    def can_confirm_answer(self):
        """See `IQuestion`."""
        if self.status not in [
            QuestionStatus.OPEN, QuestionStatus.ANSWERED,
            QuestionStatus.NEEDSINFO, QuestionStatus.SOLVED]:
            return False
        if self.answerer is not None and self.answerer is not self.owner:
            return False

        for message in self.messages:
            if message.action == QuestionAction.ANSWER:
                return True
        return False

    @notify_question_modified()
    def confirmAnswer(self, comment, answer=None, datecreated=None):
        """See `IQuestion`."""
        if not self.can_confirm_answer:
            raise InvalidQuestionStateError(
                "There is no answer that can be confirmed")
        if answer:
            assert answer in self.messages
            assert answer.owner != self.owner, (
                'Use giveAnswer() when solving own question.')

        msg = self._newMessage(
            self.owner, comment, datecreated=datecreated,
            action=QuestionAction.CONFIRM,
            new_status=QuestionStatus.SOLVED)
        if answer:
            self.date_solved = msg.datecreated
            self.answerer = answer.owner
            self.answer = answer

            self.owner.assignKarma(
                'questionansweraccepted', product=self.product,
                distribution=self.distribution,
                sourcepackagename=self.sourcepackagename)
            self.answerer.assignKarma(
                'questionanswered', product=self.product,
                distribution=self.distribution,
                sourcepackagename=self.sourcepackagename)
        return msg

    def canReject(self, user):
        """See `IQuestion`."""
        for contact in self.target.answer_contacts:
            if user.inTeam(contact):
                return True
        admin = getUtility(ILaunchpadCelebrities).admin
        # self.target can return a source package, we want the
        # pillar target.
        context = self.product or self.distribution
        return user.inTeam(context.owner) or user.inTeam(admin)

    @notify_question_modified()
    def reject(self, user, comment, datecreated=None):
        """See `IQuestion`."""
        assert self.canReject(user), (
            'User "%s" cannot reject the question.' % user.displayname)
        if self.status == QuestionStatus.INVALID:
            raise InvalidQuestionStateError("Question is already rejected.")
        msg = self._newMessage(
            user, comment, datecreated=datecreated,
            action=QuestionAction.REJECT, new_status=QuestionStatus.INVALID)
        self.answerer = user
        self.date_solved = msg.datecreated
        self.answer = msg
        return msg

    @notify_question_modified()
    def expireQuestion(self, user, comment, datecreated=None):
        """See `IQuestion`."""
        if self.status not in [QuestionStatus.OPEN, QuestionStatus.NEEDSINFO]:
            raise InvalidQuestionStateError(
                "Question status != OPEN or NEEDSINFO")
        return self._newMessage(
            user, comment, datecreated=datecreated,
            action=QuestionAction.EXPIRE, new_status=QuestionStatus.EXPIRED)

    @property
    def can_reopen(self):
        """See `IQuestion`."""
        return self.status in [
            QuestionStatus.ANSWERED, QuestionStatus.EXPIRED,
            QuestionStatus.SOLVED]

    @notify_question_modified()
    def reopen(self, comment, datecreated=None):
        """See `IQuestion`."""
        if not self.can_reopen:
            raise InvalidQuestionStateError(
                "Question status != ANSWERED, EXPIRED or SOLVED.")
        msg = self._newMessage(
            self.owner, comment, datecreated=datecreated,
            action=QuestionAction.REOPEN, new_status=QuestionStatus.OPEN)
        self.answer = None
        self.answerer = None
        self.date_solved = None
        return msg

    # subscriptions
    def subscribe(self, person):
        """See `IQuestion`."""
        # First see if a relevant subscription exists, and if so, update it.
        for sub in self.subscriptions:
            if sub.person.id == person.id:
                return sub
        # Since no previous subscription existed, create a new one.
        sub = QuestionSubscription(question=self, person=person)
        Store.of(sub).flush()
        return sub

    def unsubscribe(self, person):
        """See `IQuestion`."""
        # See if a relevant subscription exists, and if so, delete it.
        for sub in self.subscriptions:
            if sub.person.id == person.id:
                store = Store.of(sub)
                sub.destroySelf()
                store.flush()
                return

    def getSubscribers(self):
        """See `IQuestion`."""
        subscribers = self.getDirectSubscribers()
        subscribers.update(self.getIndirectSubscribers())
        return subscribers

    def getDirectSubscribers(self):
        """See `IQuestion`."""
        subscribers = NotificationRecipientSet()
        reason = ("You received this question notification because you are "
                  "a direct subscriber of the question.")
        subscribers.add(self.subscribers, reason, 'Subscriber')
        return subscribers

    def getIndirectSubscribers(self):
        """See `IQuestion`."""
        subscribers = self.target.getAnswerContactRecipients(self.language)
        if self.assignee:
            reason = ('You received this question notification because you '
                      'are the assignee for this question.')
            subscribers.add(self.assignee, reason, 'Assignee')
        return subscribers

    def _newMessage(self, owner, content, action, new_status, subject=None,
                    datecreated=None, update_question_dates=True):
        """Create a new QuestionMessage, link it to this question and update
        the question's status to new_status.

        When update_question_dates is True, the question's datelastquery or
        datelastresponse attribute is updated to the message creation date.
        The datelastquery attribute is updated when the message owner is the
        same than the question owner, otherwise the datelastresponse is updated.

        :owner: An IPerson.
        :content: A string or an IMessage. When it's an IMessage, the owner
                  must be the same than the :owner: parameter.
        :action: A QuestionAction.
        :new_status: A QuestionStatus.
        :subject: The Message subject, default to followup_subject. Ignored
                  when content is an IMessage.
        :datecreated: A datetime object which will be used as the Message
                      creation date. Ignored when content is an IMessage.
        :update_question_dates: A bool.
        """
        if IMessage.providedBy(content):
            assert owner == content.owner, (
                'The IMessage has the wrong owner.')
            msg = content
        else:
            if subject is None:
                subject = self.followup_subject
            if datecreated is None:
                datecreated = UTC_NOW
            msg = Message(
                owner=owner, rfc822msgid=make_msgid('lpquestions'),
                subject=subject, datecreated=datecreated)
            MessageChunk(message=msg, content=content, sequence=1)

        tktmsg = QuestionMessage(
            question=self, message=msg, action=action, new_status=new_status)
        notify(SQLObjectCreatedEvent(tktmsg, user=tktmsg.owner))
        # Make sure we update the relevant date of response or query.
        if update_question_dates:
            if owner == self.owner:
                self.datelastquery = msg.datecreated
            else:
                self.datelastresponse = msg.datecreated
        self.status = new_status
        return tktmsg

    # IBugLinkTarget implementation
    def linkBug(self, bug):
        """See `IBugLinkTarget`."""
        # Subscribe the question's owner to the bug.
        bug.subscribe(self.owner, self.owner)
        return BugLinkTargetMixin.linkBug(self, bug)

    def unlinkBug(self, bug):
        """See `IBugLinkTarget`."""
        buglink = BugLinkTargetMixin.unlinkBug(self, bug)
        if buglink:
            # Additionnaly, unsubscribe the question's owner to the bug
            bug.unsubscribe(self.owner)
        return buglink

    # Template methods for BugLinkTargetMixin.
    buglinkClass = QuestionBug

    def createBugLink(self, bug):
        """See BugLinkTargetMixin."""
        return QuestionBug(question=self, bug=bug)


class QuestionSet:
    """The set of questions in the Answer Tracker."""

    implements(IQuestionSet)

    def __init__(self):
        """See `IQuestionSet`."""
        self.title = 'Launchpad'

    def findExpiredQuestions(self, days_before_expiration):
        """See `IQuestionSet`."""
        # This query joins to bugtasks that are not BugTaskStatus.INVALID
        # because there are many bugtasks to one question. A question is
        # included when BugTask.status IS NULL.
        return Question.select("""
            id in (SELECT Question.id
                FROM Question
                    LEFT OUTER JOIN QuestionBug
                        ON Question.id = QuestionBug.question
                    LEFT OUTER JOIN BugTask
                        ON QuestionBug.bug = BugTask.bug
                            AND BugTask.status != %s
                WHERE
                    Question.status IN (%s, %s)
                    AND (Question.datelastresponse IS NULL
                         OR Question.datelastresponse < (CURRENT_TIMESTAMP
                            AT TIME ZONE 'UTC' - interval '%s days'))
                    AND Question.datelastquery < (CURRENT_TIMESTAMP
                            AT TIME ZONE 'UTC' - interval '%s days')
                    AND Question.assignee IS NULL
                    AND BugTask.status IS NULL)
            """ % sqlvalues(
                BugTaskStatus.INVALID,
                QuestionStatus.OPEN, QuestionStatus.NEEDSINFO,
                days_before_expiration, days_before_expiration))

    def searchQuestions(self, search_text=None, language=None,
                      status=QUESTION_STATUS_DEFAULT_SEARCH, sort=None):
        """See `IQuestionSet`"""
        return QuestionSearch(
            search_text=search_text, status=status, language=language,
            sort=sort).getResults()

    def getQuestionLanguages(self):
        """See `IQuestionSet`"""
        return set(Language.select('Language.id = Question.language',
            clauseTables=['Question'], distinct=True))

    def getMostActiveProjects(self, limit=5):
        """See `IQuestionSet`."""
        cur = cursor()
        cur.execute("""
            SELECT product, distribution, count(*) AS "question_count"
            FROM (
                SELECT product, distribution
                FROM Question
                    LEFT OUTER JOIN Product ON (Question.product = Product.id)
                    LEFT OUTER JOIN Distribution ON (
                        Question.distribution = Distribution.id)
                WHERE
                    (Product.official_answers is True
                    OR Distribution.official_answers is TRUE)
                    AND Question.datecreated > (
                        current_timestamp -interval '60 days')
                LIMIT 5000
            ) AS "RecentQuestions"
            GROUP BY product, distribution
            ORDER BY question_count DESC
            LIMIT %s
            """ % sqlvalues(limit))

        projects = []
        product_set = getUtility(IProductSet)
        distribution_set = getUtility(IDistributionSet)
        for product_id, distribution_id, ignored in cur.fetchall():
            if product_id:
                projects.append(product_set.get(product_id))
            elif distribution_id:
                projects.append(distribution_set.get(distribution_id))
            else:
                raise AssertionError(
                    'product_id and distribution_id are NULL')
        return projects

    @staticmethod
    def new(title=None, description=None, owner=None,
            product=None, distribution=None, sourcepackagename=None,
            datecreated=None, language=None):
        """Common implementation for IQuestionTarget.newQuestion()."""
        if datecreated is None:
            datecreated = UTC_NOW
        if language is None:
            language = getUtility(ILaunchpadCelebrities).english
        question = Question(
            title=title, description=description, owner=owner,
            product=product, distribution=distribution, language=language,
            sourcepackagename=sourcepackagename, datecreated=datecreated,
            datelastquery=datecreated)

        # Subscribe the submitter
        question.subscribe(owner)

        return question

    def get(self, question_id, default=None):
        """See `IQuestionSet`."""
        try:
            return Question.get(question_id)
        except SQLObjectNotFound:
            return default

    def getOpenQuestionCountByPackages(self, packages):
        """See `IQuestionSet`."""
        distributions = list(
            set(package.distribution for package in packages))
        # We can't get counts for all packages in one query, since we'd
        # need to match on (distribution, sourcepackagename). Issue one
        # query per distribution instead.
        counts = {}
        for distribution in distributions:
            counts.update(self._getOpenQuestionCountsForDistribution(
                distribution, packages))
        return counts

    def _getOpenQuestionCountsForDistribution(self, distribution, packages):
        """Get question counts by package belonging to the given distribution.

        See `IQuestionSet.getOpenQuestionCountByPackages` for more
        information.
        """
        packages = [
            package for package in packages
            if package.distribution == distribution]
        package_name_ids = [
            package.sourcepackagename.id for package in packages]
        open_statuses = [QuestionStatus.OPEN, QuestionStatus.NEEDSINFO]

        query = """
            SELECT Question.distribution,
                   Question.sourcepackagename,
                   COUNT(*) AS open_questions
            FROM Question
            WHERE Question.status IN %(open_statuses)s
                AND Question.sourcepackagename IN %(package_names)s
                AND Question.distribution = %(distribution)s
            GROUP BY Question.distribution, Question.sourcepackagename
            """ % sqlvalues(
                open_statuses=open_statuses,
                package_names=package_name_ids,
                distribution=distribution,
                )
        cur = cursor()
        cur.execute(query)
        sourcepackagename_set = getUtility(ISourcePackageNameSet)
        packages_with_questions = set()
        # Only packages with open questions are included in the query
        # result, so initialize each package to 0.
        counts = dict((package, 0) for package in packages)
        for distro_id, spn_id, open_questions in cur.fetchall():
            # The SourcePackageNames here should already be pre-fetched,
            # so that .get(spn_id) won't issue a DB query.
            sourcepackagename = sourcepackagename_set.get(spn_id)
            source_package = distribution.getSourcePackage(sourcepackagename)
            counts[source_package] = open_questions

        return counts


class QuestionSearch:
    """Base object for searching questions.

    The search parameters are specified at creation time and getResults()
    is used to retrieve the questions matching the search criteria.
    """

    def __init__(self, search_text=None, needs_attention_from=None, sort=None,
                 status=QUESTION_STATUS_DEFAULT_SEARCH, language=None,
                 product=None, distribution=None, sourcepackagename=None,
                 project=None):
        self.search_text = search_text

        if zope_isinstance(status, DBItem):
            self.status = [status]
        else:
            self.status = status

        if ILanguage.providedBy(language):
            self.language = [language]
        else:
            self.language = language

        self.sort = sort
        if needs_attention_from is not None:
            assert IPerson.providedBy(needs_attention_from), (
                "expected IPerson, got %r" % needs_attention_from)
        self.needs_attention_from = needs_attention_from

        self.product = product
        self.distribution = distribution
        self.sourcepackagename = sourcepackagename
        self.project = project

    def getTargetConstraints(self):
        """Return the constraints related to the IQuestionTarget context."""
        if self.sourcepackagename:
            assert self.distribution is not None, (
                "Distribution must be specified if sourcepackage is not None")

        constraints = []

        if self.product:
            constraints.append(
                'Question.product = %s' % sqlvalues(self.product))
        elif self.distribution:
            constraints.append(
                'Question.distribution = %s' % sqlvalues(self.distribution))
            if self.sourcepackagename:
                constraints.append(
                    'Question.sourcepackagename = %s' % sqlvalues(
                        self.sourcepackagename))
        elif self.project:
            constraints.append("""
                Question.product = Product.id AND
                Product.project = %s""" % sqlvalues(self.project))

        return constraints

    def getTableJoins(self):
        """Return the tables that should be joined for the constraints."""
        if self.needs_attention_from:
            return self.getMessageJoins(self.needs_attention_from)
        elif self.project:
            return self.getProductJoins()
        else:
            return []

    def getMessageJoins(self, person):
        """Create the joins needed to select constraints on the messages by a
        particular person."""
        joins = [
            ("""LEFT OUTER JOIN QuestionMessage
                ON QuestionMessage.question = Question.id"""),
            ("""LEFT OUTER JOIN Message
                ON QuestionMessage.message = Message.id
                AND Message.owner = %s""" % sqlvalues(person))]
        if self.project:
            joins.extend(self.getProductJoins())

        return joins

    def getProductJoins(self):
        """Create the joins needed to select contrains on progects by a
        particular project."""
        return [('JOIN Product '
                 'ON Question.product = Product.id')]

    def getConstraints(self):
        """Return a list of SQL constraints to use for this search."""

        constraints = self.getTargetConstraints()

        if self.search_text is not None:
            constraints.append(
                'Question.fti @@ ftq(%s)' % quote(self.search_text))

        if self.status:
            constraints.append('Question.status IN %s' % sqlvalues(
                list(self.status)))

        if self.needs_attention_from:
            constraints.append('''(
                (Question.owner = %(person)s
                    AND Question.status IN %(owner_status)s)
                OR (Question.owner != %(person)s AND
                    Question.status = %(open_status)s AND
                    Message.owner = %(person)s)
                )''' % sqlvalues(
                    person=self.needs_attention_from,
                    owner_status=[
                        QuestionStatus.NEEDSINFO, QuestionStatus.ANSWERED],
                    open_status=QuestionStatus.OPEN))

        if self.language:
            constraints.append(
                'Question.language IN (%s)'
                    % ', '.join(sqlvalues(*self.language)))

        return constraints

    def getPrejoins(self):
        """Return a list of tables that should be prejoined on this search."""
        # The idea is to prejoin all dependant tables, except if the
        # object will be the same in all rows because it is used as a
        # search criteria.
        if self.product or self.sourcepackagename or self.project:
            # Will always be the same product, sourcepackage, or project.
            return ['owner']
        elif self.distribution:
            # Same distribution, sourcepackagename will vary.
            return ['owner', 'sourcepackagename']
        else:
            # QuestionTarget will vary.
            return ['owner', 'product', 'distribution', 'sourcepackagename']

    def getPrejoinClauseTables(self):
        """Return a list of tables that are in the contraints"""
        if self.getConstraints().count('Question.product = Product.id'):
            return ['product']
        return []

    def getOrderByClause(self):
        """Return the ORDER BY clause to use for this search's results."""
        sort = self.sort
        if sort is None:
            if self.search_text:
                sort = QuestionSort.RELEVANCY
            else:
                sort = QuestionSort.NEWEST_FIRST
        if sort is QuestionSort.NEWEST_FIRST:
            return "-Question.datecreated"
        elif sort is QuestionSort.OLDEST_FIRST:
            return "Question.datecreated"
        elif sort is QuestionSort.STATUS:
            return ["Question.status", "-Question.datecreated"]
        elif sort is QuestionSort.RELEVANCY:
            if self.search_text:
                # SQLConstant is a workaround for bug 53455
                return [SQLConstant(
                            "-rank(Question.fti, ftq(%s))" % quote(
                                self.search_text)),
                        "-Question.datecreated"]
            else:
                return "-Question.datecreated"
        elif sort is QuestionSort.RECENT_OWNER_ACTIVITY:
            return ['-Question.datelastquery']
        else:
            raise AssertionError, "Unknown QuestionSort value: %s" % sort

    def getResults(self):
        """Return the questions that match this query."""
        query = ''
        constraints = self.getConstraints()
        if constraints:
            query += (
                'Question.id IN ('
                    'SELECT Question.id FROM Question %s WHERE %s)' % (
                        '\n'.join(self.getTableJoins()),
                        ' AND '.join(constraints)))
        return Question.select(
            query, prejoins=self.getPrejoins(),
            prejoinClauseTables=self.getPrejoinClauseTables(),
            orderBy=self.getOrderByClause())


class QuestionTargetSearch(QuestionSearch):
    """Search questions in an `IQuestionTarget` context.

    Used to implement IQuestionTarget.searchQuestions().
    """

    def __init__(self, search_text=None,
                 status=QUESTION_STATUS_DEFAULT_SEARCH,
                 language=None, sort=None, owner=None,
                 needs_attention_from=None, unsupported_target=None,
                 project=None, product=None, distribution=None,
                 sourcepackagename=None):
        assert (product is not None or distribution is not None or
            project is not None), ("Missing a product, distribution or "
                                   "project context.")
        QuestionSearch.__init__(
            self, search_text=search_text, status=status, language=language,
            needs_attention_from=needs_attention_from, sort=sort,
            project=project, product=product,
            distribution=distribution, sourcepackagename=sourcepackagename)

        if owner:
            assert IPerson.providedBy(owner), (
                "expected IPerson, got %r" % owner)
        self.owner = owner
        self.unsupported_target = unsupported_target

    def getConstraints(self):
        """See `QuestionSearch`.

        Return target and language constraints in addition to the base class
        constraints.
        """
        constraints = QuestionSearch.getConstraints(self)
        if self.owner:
            constraints.append('Question.owner = %s' % self.owner.id)
        if self.unsupported_target is not None:
            langs = [str(lang.id)
                     for lang in (
                        self.unsupported_target.getSupportedLanguages())]
            constraints.append('Question.language NOT IN (%s)' %
                               ', '.join(langs))

        return constraints

    def getPrejoins(self):
        """See `QuestionSearch`."""
        prejoins = QuestionSearch.getPrejoins(self)
        if self.owner and 'owner' in prejoins:
            # Since it is constant, no need to prefetch it.
            prejoins.remove('owner')
        return prejoins


class SimilarQuestionsSearch(QuestionSearch):
    """Search questions in a context using a similarity search algorithm.

    This search object is used to implement
    IQuestionTarget.findSimilarQuestions().
    """

    def __init__(self, title, product=None, distribution=None,
                 sourcepackagename=None):
        assert product is not None or distribution is not None, (
            "Missing a product or distribution context.")
        QuestionSearch.__init__(
            self, search_text=title, product=product,
            distribution=distribution, sourcepackagename=sourcepackagename)

        # Change the search text to use based on the native language
        # similarity search algorithm.
        self.search_text = nl_phrase_search(
            title, Question, " AND ".join(self.getTargetConstraints()))


class QuestionPersonSearch(QuestionSearch):
    """Search questions which are related to a particular person.

    Used to implement IPerson.searchQuestions().
    """

    def __init__(self, person, search_text=None,
                 status=QUESTION_STATUS_DEFAULT_SEARCH, language=None,
                 sort=None, participation=None, needs_attention=False):
        if needs_attention:
            needs_attention_from = person
        else:
            needs_attention_from = None

        QuestionSearch.__init__(
            self, search_text=search_text, status=status, language=language,
            needs_attention_from=needs_attention_from, sort=sort)

        assert IPerson.providedBy(person), "expected IPerson, got %r" % person
        self.person = person

        if not participation:
            self.participation = QuestionParticipation.items
        elif zope_isinstance(participation, Item):
            self.participation = [participation]
        else:
            self.participation = participation

    def getTableJoins(self):
        """See `QuestionSearch`.

        Return the joins for persons in addition to the base class joins.
        """
        joins = QuestionSearch.getTableJoins(self)

        if QuestionParticipation.SUBSCRIBER in self.participation:
            joins.append(
                'LEFT OUTER JOIN QuestionSubscription '
                'ON QuestionSubscription.question = Question.id'
                ' AND QuestionSubscription.person = %s' % sqlvalues(
                    self.person))

        if QuestionParticipation.COMMENTER in self.participation:
            message_joins = self.getMessageJoins(self.person)
            if not set(joins).intersection(set(message_joins)):
                joins.extend(message_joins)

        return joins

    queryByParticipationType = {
        QuestionParticipation.ANSWERER: "Question.answerer = %s",
        QuestionParticipation.SUBSCRIBER: "QuestionSubscription.person = %s",
        QuestionParticipation.OWNER: "Question.owner = %s",
        QuestionParticipation.COMMENTER: "Message.owner = %s",
        QuestionParticipation.ASSIGNEE: "Question.assignee = %s"}

    def getConstraints(self):
        """See `QuestionSearch`.

        Return the base class constraints plus additional constraints upon
        the Person's participation in Questions.
        """
        constraints = QuestionSearch.getConstraints(self)

        participations_filter = []
        for participation_type in self.participation:
            participations_filter.append(
                self.queryByParticipationType[participation_type] % sqlvalues(
                    self.person))

        if participations_filter:
            constraints.append('(' + ' OR '.join(participations_filter) + ')')

        return constraints


class QuestionTargetMixin:
    """Mixin class for `IQuestionTarget`."""

    def getTargetTypes(self):
        """Return a Dict of QuestionTargets representing this object.

        :Return: a Dict with product, distribution, and sourcepackagename
                 as possible keys. Each value is a valid QuestionTarget
                 or None.
        """
        return {}

    def newQuestion(self, owner, title, description, language=None,
        datecreated=None):
        """See `IQuestionTarget`."""
        question = QuestionSet.new(
            title=title, description=description, owner=owner,
            datecreated=datecreated, language=language,
            **self.getTargetTypes())
        notify(SQLObjectCreatedEvent(question))
        return question

    def createQuestionFromBug(self, bug):
        """See `IQuestionTarget`."""
        question = self.newQuestion(
            bug.owner, bug.title, bug.description,
            datecreated=bug.datecreated)
        # Give the datelastresponse a current datetime, otherwise the
        # Launchpad Janitor would quickly expire questions made from old bugs.
        question.datelastresponse = datetime.now(pytz.timezone('UTC'))
        question.linkBug(bug)
        for message in bug.messages[1:]:
            # Bug.message[0] is the original message, and probably a duplicate
            # of Bug.description.
            question.addComment(
                message.owner, message.text_contents,
                datecreated=message.datecreated)
        return question

    def getQuestion(self, question_id):
        """See `IQuestionTarget`."""
        try:
            question = Question.get(question_id)
        except SQLObjectNotFound:
            return None
        # Verify that the question is actually for this target.
        if not self.questionIsForTarget(question):
            return None
        return question

    def questionIsForTarget(self, question):
        """Verify that this question is actually for this target."""
        if question.target is not self:
            return False
        return True

    def findSimilarQuestions(self, title):
        """See `IQuestionTarget`."""
        return SimilarQuestionsSearch(
            title, **self.getTargetTypes()).getResults()

    def getQuestionLanguages(self):
        """See `IQuestionTarget`."""
        constraints = ['Language.id = Question.language']
        targets = self.getTargetTypes()
        for column, target in targets.items():
            if target is None:
                constraint = "Question." + column + " IS NULL"
            else:
                constraint = "Question." + column + " = %s" % sqlvalues(
                    target)
            constraints.append(constraint)
        return set(Language.select(
            ' AND '.join(constraints),
            clauseTables=['Question'], distinct=True))

    @property
    def answer_contacts(self):
        """See `IQuestionTarget`."""
        answer_contacts = AnswerContact.selectBy(**self.getTargetTypes())
        return sorted(
            [answer_contact.person for answer_contact in answer_contacts],
            key=operator.attrgetter('displayname'))

    @property
    def direct_answer_contacts(self):
        """See `IQuestionTarget`."""
        return self.answer_contacts

    def addAnswerContact(self, person):
        """See `IQuestionTarget`."""
        answer_contact = AnswerContact.selectOneBy(
            person=person, **self.getTargetTypes())
        if answer_contact is not None:
            return False
        # Person must speak a language to be an answer contact.
        assert person.languages.count() > 0, (
            "An Answer Contact must speak a language.")
        params = dict(product=None, distribution=None, sourcepackagename=None)
        params.update(self.getTargetTypes())
        answer_contact = AnswerContact(person=person, **params)
        Store.of(answer_contact).flush()
        return True

    def _selectPersonFromAnswerContacts(self, constraints, clause_tables):
        """Return the Persons or Teams who are AnswerContacts."""
        answer_contacts = AnswerContact.select(
            " AND ".join(constraints), clauseTables=clause_tables,
            distinct=True)
        return sorted(
            [answer_contact.person for answer_contact in answer_contacts],
            key=operator.attrgetter('displayname'))

    def getAnswerContactsForLanguage(self, language):
        """See `IQuestionTarget`."""
        assert language is not None, (
            "The language cannot be None when selecting answer contacts.")
        constraints = []
        targets = self.getTargetTypes()
        for column, target in targets.items():
            if target is None:
                constraint = "AnswerContact." + column + " IS NULL"
            else:
                constraint = "AnswerContact." + column + " = %s" % sqlvalues(
                    target)
            constraints.append(constraint)

        constraints.append("""
            AnswerContact.person = PersonLanguage.person AND
            PersonLanguage.Language = Language.id""")
        # XXX sinzui 2007-07-12 bug=125545:
        # Using a LIKE constraint is suboptimal. We would not need this
        # if-else clause if variant languages knew their parent language.
        if language.code == 'en':
            constraints.append("""
                Language.code LIKE %s""" % sqlvalues('%s%%' % language.code))
        else:
            constraints.append("""
                Language.id = %s""" % sqlvalues(language))
        return set(self._selectPersonFromAnswerContacts(
            constraints, ['PersonLanguage', 'Language']))

    def getAnswerContactRecipients(self, language):
        """See `IQuestionTarget`."""
        if language is None:
            contacts = self.answer_contacts
        else:
            contacts = self.getAnswerContactsForLanguage(language)
        recipients = NotificationRecipientSet()
        for person in contacts:
            reason_start = (
                "You received this question notification because you are ")
            if person.isTeam():
                reason = reason_start + (
                    'a member of %s, which is an answer contact for %s.' % (
                        person.displayname, self.displayname))
                header = 'Answer Contact (%s) @%s' % (self.name, person.name)
            else:
                reason = reason_start + (
                    'an answer contact for %s.' % self.displayname)
                header = 'Answer Contact (%s)' % self.displayname
            recipients.add(person, reason, header)
        return recipients

    def removeAnswerContact(self, person):
        """See `IQuestionTarget`."""
        if person not in self.answer_contacts:
            return False
        answer_contact = AnswerContact.selectOneBy(
            person=person, **self.getTargetTypes())
        if answer_contact is None:
            return False
        store = Store.of(answer_contact)
        answer_contact.destroySelf()
        store.flush()
        return True

    def getSupportedLanguages(self):
        """See `IQuestionTarget`."""
        languages = set()
        for contact in self.answer_contacts:
            languages |= set(contact.languages)
        languages.add(getUtility(ILaunchpadCelebrities).english)
        languages = set(
            lang for lang in languages if not is_english_variant(lang))
        return languages
