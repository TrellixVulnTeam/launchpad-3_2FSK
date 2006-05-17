# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Interfaces declarations for external bugtrackers."""

__metaclass__ = type

__all__ = [
    'IExternalBugtracker',
    'UNKNOWN_REMOTE_STATUS',
    ]

from zope.interface import Interface

# This is a text string which indicates that the remote status is
# unknown for some reason.
# XXX: We should store the actual reason for the error somewhere. This
#      would allow us to get rid of this text constant. Bug XXX.
UNKNOWN_REMOTE_STATUS = 'UNKNOWN'


class IExternalBugtracker(Interface):
    """A class used to talk with an external bug tracker."""

    def updateBugWatches(bug_watches):
        """Update the given bug watches."""

    def convertRemoteStatus(remote_status):
        """Converts the remote status string to a BugTaskStatus item."""
