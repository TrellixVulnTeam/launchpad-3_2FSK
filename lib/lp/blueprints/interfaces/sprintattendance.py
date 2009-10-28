# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Sprint Attendance interfaces."""

__metaclass__ = type

__all__ = [
    'ISprintAttendance',
    ]

from zope.interface import Interface
from zope.schema import Bool, Choice, Datetime
from canonical.launchpad import _
from canonical.launchpad.fields import PublicPersonChoice


class ISprintAttendance(Interface):
    """An attendance of a person at a sprint."""

    attendee = PublicPersonChoice(
        title=_('Attendee'), required=True, vocabulary='ValidPersonOrTeam')
    sprint = Choice(title=_('The Sprint'), required=True,
        vocabulary='Sprint',
        description=_("Select the meeting from the list presented above."))
    time_starts = Datetime(title=_('From'), required=True,
        description=_("The date and time of arrival and "
        "availability for sessions during the sprint."))
    time_ends = Datetime(title=_('To'), required=True,
        description=_("The date and time of your departure. "
        "Please ensure the time reflects accurately "
        "when you will no longer be available for sessions at this event, to "
        "assist those planning the schedule."))
    is_physical = Bool(
        title=_("Will you be physically present?"),
        description=_("False implies your attendance is virtual."),
        required=False, readonly=False, default=False)
