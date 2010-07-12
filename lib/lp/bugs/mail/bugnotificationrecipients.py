# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Code for handling bug notification recipients in bug mail."""

__metaclass__ = type
__all__ = [
    'BugNotificationRecipients',
    ]

from zope.interface import implements

from canonical.launchpad.interfaces import INotificationRecipientSet

from lp.services.mail.basemailer import RecipientReason
from lp.services.mail.notificationrecipientset import (
    NotificationRecipientSet)


class BugNotificationRecipientReason(RecipientReason):
    """A `RecipientReason` subsclass specifically for `BugNotification`s."""

    @classmethod
    def _getReasonTemplate(cls, reason_string):
        """Return a reason template to pass to __init__()."""
        reason_base = (
            "You received this bug notification because %(lc_entity_is)s")
        return "%s %s." % (reason_base, reason_string)

    @classmethod
    def forDupeSubscriber(cls, person, duplicate_bug):
        """Return a `BugNotificationRecipientReason` for a dupe subscriber.
        """
        header = "%s via Bug %s" % (
            cls.makeRationale('Subscriber to Duplicate', person),
            duplicate_bug.id)

        reason = cls._getReasonTemplate(
            "a direct subscriber to duplicate bug %s" %  duplicate_bug.id)
        return cls(person, person, header, reason)

    @classmethod
    def forDirectSubscriber(cls, person):
        """Return a `BugNotificationRecipientReason` for a direct subscriber.
        """
        header = cls.makeRationale("Subscriber", person)
        reason = cls._getReasonTemplate("a direct subscriber to the bug")
        return cls(person, person, header, reason)

    @classmethod
    def forAssignee(cls, person):
        """Return a `BugNotificationRecipientReason` for a bug assignee."""
        header = cls.makeRationale("Assignee", person)
        reason = cls._getReasonTemplate("a bug assignee")
        return cls(person, person, header, reason)

    @classmethod
    def forBugSupervisor(cls, person, target):
        """Return a `BugNotificationRecipientReason` for a bug supervisor."""
        header = cls.makeRationale(
            "Bug Supervisor (%s)" % target.displayname, person)
        reason = cls._getReasonTemplate(
            "the bug supervisor for %s" % target.displayname)
        return cls(person, person, header, reason)

    @classmethod
    def forStructuralSubscriber(cls, person, target):
        """Return a recipient reason for a structural subscriber."""
        header = cls.makeRationale(
            "Subscriber (%s)" % target.displayname, person)
        reason = cls._getReasonTemplate(
            "subscribed to %s" % target.displayname)
        return cls(person, person, header, reason)

    @classmethod
    def forRegistrant(cls, person, upstream):
        """..."""


class BugNotificationRecipients(NotificationRecipientSet):
    """A set of emails and rationales notified for a bug change.

    Each email address registered in a BugNotificationRecipients is
    associated to a string and a header that explain why the address is
    being emailed. For instance, if the email address is that of a
    distribution bug supervisor for a bug, the string and header will make
    that fact clear.

    The string is meant to be rendered in the email footer. The header
    is meant to be used in an X-Launchpad-Message-Rationale header.

    The first rationale registered for an email address is the one
    which will be used, regardless of other rationales being added
    for it later. This gives us a predictable policy of preserving
    the first reason added to the registry; the callsite should
    ensure that the manipulation of the BugNotificationRecipients
    instance is done in preferential order.

    Instances of this class are meant to be returned by
    IBug.getBugNotificationRecipients().
    """
    implements(INotificationRecipientSet)

    def __init__(self, duplicateof=None):
        """Constructs a new BugNotificationRecipients instance.

        If this bug is a duplicate, duplicateof should be used to
        specify which bug ID it is a duplicate of.

        Note that there are two duplicate situations that are
        important:
          - One is when this bug is a duplicate of another bug:
            the subscribers to the main bug get notified of our
            changes.
          - Another is when the bug we are changing has
            duplicates; in that case, direct subscribers of
            duplicate bugs get notified of our changes.
        These two situations are catered respectively by the
        duplicateof parameter above and the addDupeSubscriber method.
        Don't confuse them!
        """
        NotificationRecipientSet.__init__(self)
        self.duplicateof = duplicateof

    def _addReason(self, person, reason, header):
        """Adds a reason (text and header) for a person.

        It takes care of modifying the message when the person is notified
        via a duplicate.
        """
        if self.duplicateof is not None:
            reason = reason + " (via bug %s)" % self.duplicateof.id
            header = header + " via Bug %s" % self.duplicateof.id
        reason = "You received this bug notification because you %s." % reason
        self.add(person, reason, header)

    def addDupeSubscriber(self, person):
        """Registers a subscriber of a duplicate of this bug."""
        reason = "Subscriber of Duplicate"
        if person.isTeam():
            text = ("are a member of %s, which is a subscriber "
                    "of a duplicate bug" % person.displayname)
            reason += " @%s" % person.name
        else:
            text = "are a direct subscriber of a duplicate bug"
        self._addReason(person, text, reason)

    def addDirectSubscriber(self, person):
        """Registers a direct subscriber of this bug."""
        reason = "Subscriber"
        if person.isTeam():
            text = ("are a member of %s, which is a direct subscriber"
                    % person.displayname)
            reason += " @%s" % person.name
        else:
            text = "are a direct subscriber of the bug"
        self._addReason(person, text, reason)

    def addAssignee(self, person):
        """Registers an assignee of a bugtask of this bug."""
        reason = "Assignee"
        if person.isTeam():
            text = ("are a member of %s, which is a bug assignee"
                    % person.displayname)
            reason += " @%s" % person.name
        else:
            text = "are a bug assignee"
        self._addReason(person, text, reason)

    def addDistroBugSupervisor(self, person, distro):
        """Registers a distribution bug supervisor for this bug."""
        reason = "Bug Supervisor (%s)" % distro.displayname
        # All displaynames in these reasons should be changed to bugtargetname
        # (as part of bug 113262) once bugtargetname is finalized for packages
        # (bug 113258). Changing it before then would be excessively
        # disruptive.
        if person.isTeam():
            text = ("are a member of %s, which is the bug supervisor for %s" %
                (person.displayname, distro.displayname))
            reason += " @%s" % person.name
        else:
            text = "are the bug supervisor for %s" % distro.displayname
        self._addReason(person, text, reason)

    def addStructuralSubscriber(self, person, target):
        """Registers a structural subscriber to this bug's target."""
        reason = "Subscriber (%s)" % target.displayname
        if person.isTeam():
            text = ("are a member of %s, which is subscribed to %s" %
                (person.displayname, target.displayname))
            reason += " @%s" % person.name
        else:
            text = "are subscribed to %s" % target.displayname
        self._addReason(person, text, reason)

    def addUpstreamBugSupervisor(self, person, upstream):
        """Registers an upstream bug supervisor for this bug."""
        reason = "Bug Supervisor (%s)" % upstream.displayname
        if person.isTeam():
            text = ("are a member of %s, which is the bug supervisor for %s" %
                (person.displayname, upstream.displayname))
            reason += " @%s" % person.name
        else:
            text = "are the bug supervisor for %s" % upstream.displayname
        self._addReason(person, text, reason)

    def addRegistrant(self, person, upstream):
        """Registers an upstream product registrant for this bug."""
        reason = "Registrant (%s)" % upstream.displayname
        if person.isTeam():
            text = ("are a member of %s, which is the registrant for %s" %
                (person.displayname, upstream.displayname))
            reason += " @%s" % person.name
        else:
            text = "are the registrant for %s" % upstream.displayname
        self._addReason(person, text, reason)



