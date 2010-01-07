# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy
from zope.proxy import isProxy
from zope.schema.vocabulary import getVocabularyRegistry
from lazr.enum import BaseItem

from canonical.database.constants import UTC_NOW
from lp.bugs.adapters.bugchange import (
    CveLinkedToBug, CveUnlinkedFromBug)
from canonical.database.sqlbase import block_implicit_flushes
from lp.bugs.adapters.bugchange import (
    BugWatchAdded, BugWatchRemoved)
from lp.bugs.interfaces.bug import IBug
from lp.bugs.interfaces.bugactivity import IBugActivitySet
from lp.registry.interfaces.milestone import IMilestone, IProductRelease
from lp.registry.interfaces.person import IPerson
from lp.soyuz.interfaces.sourcepackagerelease import ISourcePackageRelease
from lp.bugs.adapters.bugchange import BugTaskAdded

vocabulary_registry = getVocabularyRegistry()


BUG_INTERESTING_FIELDS = [
    'name',
    ]


def get_string_representation(obj):
    """Returns a string representation of an object.

    It can be used as oldvalue and newvalue.

    Returns None if no representation can be made.
    """
    if IPerson.providedBy(obj):
        return obj.name
    if IBug.providedBy(obj):
        return str(obj.id)
    elif ISourcePackageRelease.providedBy(obj):
        return "%s %s" % (obj.sourcepackagename.name, obj.version)
    elif IProductRelease.providedBy(obj):
        return "%s %s" % (obj.product.name, obj.version)
    elif IMilestone.providedBy(obj):
        return obj.name
    elif isinstance(obj, BaseItem):
        return obj.title
    elif isinstance(obj, basestring):
        return obj
    elif isinstance(obj, bool):
        return str(obj)
    else:
        return None


def what_changed(sqlobject_modified_event):
    before = sqlobject_modified_event.object_before_modification
    after = sqlobject_modified_event.object
    fields = sqlobject_modified_event.edited_fields
    changes = {}
    for fieldname in fields:
        val_before = getattr(before, fieldname, None)
        val_after = getattr(after, fieldname, None)

        #XXX Bjorn Tillenius 2005-06-09: This shouldn't be necessary.
        # peel off the zope stuff
        if isProxy(val_before):
            val_before = removeSecurityProxy(val_before)
        if isProxy(val_after):
            val_after = removeSecurityProxy(val_after)

        before_string = get_string_representation(val_before)
        after_string = get_string_representation(val_after)

        if before_string != after_string:
            changes[fieldname] = [before_string, after_string]

    return changes


@block_implicit_flushes
def record_bug_added(bug, object_created_event):
    getUtility(IBugActivitySet).new(
        bug = bug.id,
        datechanged = UTC_NOW,
        person = IPerson(object_created_event.user),
        whatchanged = "bug",
        message = "added bug")


@block_implicit_flushes
def record_bug_edited(bug_edited, sqlobject_modified_event):
    # If the event was triggered by a web service named operation, its
    # edited_fields will be empty. We'll need to check all interesting
    # fields to see which were actually changed.
    sqlobject_modified_event.edited_fields = BUG_INTERESTING_FIELDS

    changes = what_changed(sqlobject_modified_event)
    for changed_field in changes:
        oldvalue, newvalue = changes[changed_field]
        getUtility(IBugActivitySet).new(
            bug=bug_edited.id,
            datechanged=UTC_NOW,
            person=IPerson(sqlobject_modified_event.user),
            whatchanged=changed_field,
            oldvalue=oldvalue,
            newvalue=newvalue,
            message="")


@block_implicit_flushes
def record_cve_linked_to_bug(bug_cve, event):
    """Record when a CVE is linked to a bug."""
    bug_cve.bug.addChange(
        CveLinkedToBug(
            when=None,
            person=IPerson(event.user),
            cve=bug_cve.cve))


@block_implicit_flushes
def record_cve_unlinked_from_bug(bug_cve, event):
    """Record when a CVE is unlinked from a bug."""
    bug_cve.bug.addChange(
        CveUnlinkedFromBug(
            when=None,
            person=IPerson(event.user),
            cve=bug_cve.cve))


@block_implicit_flushes
def record_bugsubscription_added(bugsubscription_added, object_created_event):
    getUtility(IBugActivitySet).new(
        bug=bugsubscription_added.bug,
        datechanged=UTC_NOW,
        person=IPerson(object_created_event.user),
        whatchanged='bug',
        message='added subscriber %s' % (
            bugsubscription_added.person.displayname))


@block_implicit_flushes
def record_bugsubscription_edited(bugsubscription_edited,
                                  sqlobject_modified_event):
    changes = what_changed(sqlobject_modified_event)
    if changes:
        for changed_field in changes.keys():
            oldvalue, newvalue = changes[changed_field]
            getUtility(IBugActivitySet).new(
                bug=bugsubscription_edited.bug,
                datechanged=UTC_NOW,
                person=IPerson(sqlobject_modified_event.user),
                whatchanged="subscriber %s" % (
                    bugsubscription_edited.person.displayname),
                oldvalue=oldvalue,
                newvalue=newvalue)


@block_implicit_flushes
def notify_bugtask_added(bugtask, event):
    """Notify CC'd list that this bug has been marked as needing fixing
    somewhere else.

    bugtask must be in IBugTask. event must be an
    IObjectModifiedEvent.
    """
    bugtask.bug.addChange(BugTaskAdded(UTC_NOW, IPerson(event.user), bugtask))


@block_implicit_flushes
def notify_bug_watch_modified(modified_bug_watch, event):
    """Notify CC'd bug subscribers that a bug watch was edited.

    modified_bug_watch must be an IBugWatch. event must be an
    IObjectModifiedEvent.
    """
    old_watch = event.object_before_modification
    new_watch = event.object
    bug = new_watch.bug
    if old_watch.url == new_watch.url:
        # Nothing interesting was modified, don't record any changes.
        return
    bug.addChange(BugWatchRemoved(UTC_NOW, IPerson(event.user), old_watch))
    bug.addChange(BugWatchAdded(UTC_NOW, IPerson(event.user), new_watch))
