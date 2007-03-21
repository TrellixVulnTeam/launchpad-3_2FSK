# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

""" karma.py -- handles all karma assignments done in the launchpad
application."""

from canonical.launchpad.interfaces import IDistroBugTask, IDistroReleaseBugTask
from canonical.launchpad.mailnotification import get_bug_delta
from canonical.lp.dbschema import BugTaskStatus, QuestionAction


def bug_created(bug, event):
    """Assign karma to the user which created <bug>."""
    # All newly created bugs get at least one bugtask associated with
    assert len(bug.bugtasks) >= 1
    _assignKarmaUsingBugContext(event.user, bug, 'bugcreated')

def _assign_karma_using_bugtask_context(person, bugtask, actionname):
    """Extract the right context from the bugtask and assign karma."""
    distribution = bugtask.distribution
    if bugtask.distrorelease is not None:
        # This is a Distro Release Task, so distribution is None and we
        # have to get it from the distrorelease.
        distribution = bugtask.distrorelease.distribution
    product = bugtask.product
    if bugtask.productseries is not None:
        product = bugtask.productseries.product
    person.assignKarma(
        actionname, product=product, distribution=distribution,
        sourcepackagename=bugtask.sourcepackagename)


def bugtask_created(bugtask, event):
    """Assign karma to the user which created <bugtask>."""
    _assign_karma_using_bugtask_context(event.user, bugtask, 'bugtaskcreated')


def _assignKarmaUsingBugContext(person, bug, actionname):
    """For each of the given bug's bugtasks, assign Karma with the given
    actionname to the given person.
    """
    for task in bug.bugtasks:
        if task.status == BugTaskStatus.REJECTED:
            continue
        _assign_karma_using_bugtask_context(person, task, actionname)


def bug_comment_added(bugmessage, event):
    """Assign karma to the user which added <bugmessage>."""
    _assignKarmaUsingBugContext(event.user, bugmessage.bug, 'bugcommentadded')


def bug_modified(bug, event):
    """Check changes made to <bug> and assign karma to user if needed."""
    user = event.user
    bug_delta = get_bug_delta(
        event.object_before_modification, event.object, user)

    assert bug_delta is not None

    attrs_actionnames = {'title': 'bugtitlechanged',
                         'description': 'bugdescriptionchanged',
                         'duplicateof': 'bugmarkedasduplicate'}

    for attr, actionname in attrs_actionnames.items():
        if getattr(bug_delta, attr) is not None:
            _assignKarmaUsingBugContext(user, bug, actionname)


def bugwatch_added(bugwatch, event):
    """Assign karma to the user which added :bugwatch:."""
    _assignKarmaUsingBugContext(event.user, bugwatch.bug, 'bugwatchadded')


def cve_added(cve, event):
    """Assign karma to the user which added :cve:."""
    _assignKarmaUsingBugContext(event.user, cve.bug, 'bugcverefadded')


def extref_added(extref, event):
    """Assign karma to the user which added :extref:."""
    _assignKarmaUsingBugContext(event.user, extref.bug, 'bugextrefadded')


def bugtask_modified(bugtask, event):
    """Check changes made to <bugtask> and assign karma to user if needed."""
    user = event.user
    task_delta = event.object.getDelta(event.object_before_modification)

    assert task_delta is not None

    actionname_status_mapping = {
        BugTaskStatus.FIXRELEASED: 'bugfixed',
        BugTaskStatus.REJECTED: 'bugrejected',
        BugTaskStatus.CONFIRMED: 'bugaccepted'}

    if task_delta.status:
        new_status = task_delta.status['new']
        actionname = actionname_status_mapping.get(new_status)
        if actionname is not None:
            _assign_karma_using_bugtask_context(user, bugtask, actionname)

    if task_delta.importance is not None:
        _assign_karma_using_bugtask_context(
            user, bugtask, 'bugtaskimportancechanged')


def spec_created(spec, event):
    """Assign karma to the user who created the spec."""
    event.user.assignKarma(
        'addspec', product=spec.product, distribution=spec.distribution)


def spec_modified(spec, event):
    """Check changes made to the spec and assign karma if needed."""
    user = event.user
    spec_delta = event.object.getDelta(event.object_before_modification, user)
    if spec_delta is None:
        return

    # easy 1-1 mappings from attribute changing to karma
    attrs_actionnames = {
        'title': 'spectitlechanged',
        'summary': 'specsummarychanged',
        'specurl': 'specurlchanged',
        'priority': 'specpriority',
        'productseries': 'specseries',
        'distrorelease': 'specrelease',
        'milestone': 'specmilestone',
        }

    for attr, actionname in attrs_actionnames.items():
        if getattr(spec_delta, attr, None) is not None:
            user.assignKarma(
                actionname, product=spec.product,
                distribution=spec.distribution)


def _assignKarmaUsingQuestionContext(person, question, actionname):
    """Assign Karma with the given actionname to the given person.

    Use the given question's context as the karma context.
    """
    person.assignKarma(
        actionname, product=question.product, 
	distribution=question.distribution,
        sourcepackagename=question.sourcepackagename)


def question_created(question, event):
    """Assign karma to the user which created <question>."""
    _assignKarmaUsingQuestionContext(question.owner, question, 'ticketcreated')


def question_modified(question, event):
    """Check changes made to <question> and assign karma to user if needed."""
    user = event.user
    old_question = event.object_before_modification

    if old_question.description != question.description:
        _assignKarmaUsingQuestionContext(
            user, question, 'ticketdescriptionchanged')

    if old_question.title != question.title:
        _assignKarmaUsingQuestionContext(user, question, 'tickettitlechanged')


QuestionAction2KarmaAction = {
    QuestionAction.REQUESTINFO: 'ticketrequestedinfo',
    QuestionAction.GIVEINFO: 'ticketgaveinfo',
    QuestionAction.SETSTATUS: None,
    QuestionAction.COMMENT: 'ticketcommentadded',
    QuestionAction.ANSWER: 'ticketgaveanswer',
    QuestionAction.CONFIRM: None, # Handled in giveAnswer() and confirmAnswer()
    QuestionAction.EXPIRE: None,
    QuestionAction.REJECT: 'ticketrejected',
    QuestionAction.REOPEN: 'ticketreopened',
}


def question_comment_added(questionmessage, event):
    """Assign karma to the user which added <questionmessage>."""
    question = questionmessage.question
    karma_action = QuestionAction2KarmaAction.get(questionmessage.action)
    if karma_action:
        _assignKarmaUsingQuestionContext(
            questionmessage.owner, question, karma_action)


def question_bug_added(questionbug, event):
    """Assign karma to the user which added <questionbug>."""
    question = questionbug.question
    _assignKarmaUsingQuestionContext(event.user, question, 'ticketlinkedtobug')

