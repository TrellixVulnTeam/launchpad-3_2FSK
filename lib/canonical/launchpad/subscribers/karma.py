# Copyright 2004 Canonical Ltd.  All rights reserved.

""" karma.py -- handles all karma assignments done in the launchpad
application."""

from zope.component import getUtility

from canonical.launchpad.interfaces import IPersonSet
from canonical.launchpad.mailnotification import get_bug_delta, get_task_delta
from canonical.lp.dbschema import (BugTaskStatus,
     RosettaImportStatus, RosettaTranslationOrigin)


def bug_created(bug, event):
    """Assign karma to the user which created <bug>."""
    bug.owner.assignKarma('bugcreated')


def bugtask_created(bug, event):
    """Assign karma to the user which created <bugtask>."""
    bug.owner.assignKarma('bugtaskcreated')


def bug_comment_added(bugmessage, event):
    """Assign karma to the user which added <bugmessage>."""
    bugmessage.message.owner.assignKarma('bugcommentadded')


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
            user.assignKarma(actionname)


def bugwatch_added(bugwatch, event):
    """Assign karma to the user which added :bugwatch:."""
    event.user.assignKarma('bugwatchadded')


def cve_added(cve, event):
    """Assign karma to the user which added :cve:."""
    event.user.assignKarma('bugcverefadded')


def extref_added(extref, event):
    """Assign karma to the user which added :extref:."""
    event.user.assignKarma('bugextrefadded')


def bugtask_modified(bugtask, event):
    """Check changes made to <bugtask> and assign karma to user if needed."""
    user = event.user
    task_delta = get_task_delta(event.object_before_modification, event.object)

    assert task_delta is not None

    if task_delta.status:
        new_status = task_delta.status['new']
        if new_status == BugTaskStatus.FIXRELEASED:
            user.assignKarma('bugfixed')
        elif new_status == BugTaskStatus.REJECTED:
            user.assignKarma('bugrejected')
        elif new_status == BugTaskStatus.CONFIRMED:
            user.assignKarma('bugaccepted')

    if task_delta.severity is not None:
        event.user.assignKarma('bugtaskseveritychanged')

    if task_delta.priority is not None:
        event.user.assignKarma('bugtaskprioritychanged')

def translation_import_queue_entry_modified(entry, event):
    """Check changes made to <entry> and assign karma to user if needed."""
    user = event.user
    old = event.object_before_modification
    new = event.object

    if (old.status != new.status and
        new.status == RosettaImportStatus.IMPORTED and
        new.is_published):
        if new.path.endswith('.po'):
            # A new .po file from upstream has been imported. The karma goes
            # to the one that attached the file.
            new.importer.assignKarma('translationimportupstream')
        elif new.path.endswith('.pot'):
            # A new .pot file has accepted to be imported. The karma goes to
            # the one that attached the file.
            new.importer.assignKarma('translationtemplateimport')
        else:
            # The imported file is for a new file format that we don't know
            # about.
            raise AssertionError(
                'When adding a new file format you need to update the karma'
                ' code too.')

def potemplate_modified(template, event):
    """Check changes made to <template> and assign karma to user if needed."""
    user = event.user
    old = event.object_before_modification
    new = event.object

    if old.description != new.description:
        user.assignKarma('translationtemplatedescriptionchanged')

def posubmission_created(submission, event):
    """Assign karma to the user which created <submission> if it comes from
    the web.
    """
    if (submission.person is not None and
        submission.origin == RosettaTranslationOrigin.ROSETTAWEB):
        submission.person.assignKarma('translationsuggestionadded')


def poselection_created(selection, event):
    """Assign karma to the submission author and the reviewer."""
    reviewer = event.user
    active = selection.activesubmission
    published = selection.publishedsubmission

    if (active is not None and published is not None and
        active.id == published.id):
        # The translation came from a published file so we don't add karma.
        return

    if (active is not None and
        active.person is not None and
        reviewer != active.person):
        # Only add Karma when you are not reviewing your own translations.
        active.person.assignKarma('translationsuggestionapproved')
        reviewer.assignKarma('translationreview')


def poselection_modified(selection, event):
    """Assign karma to the submission author and the reviewer."""
    reviewer = event.user
    old = event.object_before_modification
    new = event.object

    if (old.activesubmission != new.activesubmission and
        new.activesubmission is not None and
        new.activesubmission.person is not None and
        reviewer != new.activesubmission.person):
        # Only add Karma when you are not reviewing your own translations.
        new.activesubmission.person.assignKarma('translationsuggestionapproved')
        if reviewer is not None:
            reviewer.assignKarma('translationreview')

def spec_created(spec, event):
    """Assign karma to the user who created the spec."""
    spec.owner.assignKarma('addspec')

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
            user.assignKarma(actionname)


