# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The innards of the Bug Heat cronscript."""

__metaclass__ = type
__all__ = [
    'BugHeatCalculator',
    ]

from datetime import datetime

from lp.bugs.interfaces.bugtask import RESOLVED_BUGTASK_STATUSES

class BugHeatConstants:

    PRIVACY = 150
    SECURITY = 250
    DUPLICATE = 6
    AFFECTED_USER = 4
    SUBSCRIBER = 2


class BugHeatCalculator:
    """A class to calculate the heat for a bug."""

    def __init__(self, bug):
        self.bug = bug

    def _getHeatFromPrivacy(self):
        """Return the heat generated by the bug's `private` attribute."""
        if self.bug.private:
            return BugHeatConstants.PRIVACY
        else:
            return 0

    def _getHeatFromSecurity(self):
        """Return the heat generated if the bug is security related."""
        if self.bug.security_related:
            return BugHeatConstants.SECURITY
        else:
            return 0

    def _getHeatFromDuplicates(self):
        """Return the heat generated by the bug's duplicates."""
        return self.bug.duplicates.count() * BugHeatConstants.DUPLICATE

    def _getHeatFromAffectedUsers(self):
        """Return the heat generated by the bug's affected users."""
        return (
            self.bug.users_affected_count_with_dupes *
            BugHeatConstants.AFFECTED_USER)

    def _getHeatFromSubscribers(self):
        """Return the heat generated by the bug's subscribers."""
        direct_subscribers = self.bug.getDirectSubscribers()
        subscribers_from_dupes = self.bug.getSubscribersFromDuplicates()

        subscriber_count = (
            len(direct_subscribers) + len(subscribers_from_dupes))
        return subscriber_count * BugHeatConstants.SUBSCRIBER

    def _bugIsComplete(self):
        """Are all the tasks for this bug resolved?"""
        return all([(task.status in RESOLVED_BUGTASK_STATUSES)
                    for task in self.bug.bugtasks])

    def getBugHeat(self):
        """Return the total heat for the current bug."""
        if self._bugIsComplete():
            return 0

        total_heat = sum([
            self._getHeatFromAffectedUsers(),
            self._getHeatFromDuplicates(),
            self._getHeatFromPrivacy(),
            self._getHeatFromSecurity(),
            self._getHeatFromSubscribers(),
            ])

        # Bugs decay over time. Every month the bug isn't touched its heat
        # decreases by 10%.
        months = (
            datetime.utcnow() -
            self.bug.date_last_updated.replace(tzinfo=None)).days / 30
        total_heat = int(total_heat * (0.9 ** months))

        return total_heat

