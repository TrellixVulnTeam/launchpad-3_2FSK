# Copyright 2005 Canonical Ltd

"""
Calendaring for Launchpad

This package contains various components that don't fit into database/
or browser/.
"""

__metaclass__ = type

from zope.interface import implements
from zope.component import getUtility

from canonical.launchpad import _
from schoolbell.interfaces import ICalendar
from canonical.launchpad.interfaces import (
    ILaunchBag, ILaunchpadCalendar, ILaunchpadMergedCalendar,
    ICalendarSubscriptionSubset)

from schoolbell.mixins import CalendarMixin, EditableCalendarMixin
from schoolbell.icalendar import convert_calendar_to_ical


def calendarFromCalendarOwner(calendarowner):
    """Adapt ICalendarOwner to ICalendar."""
    return calendarowner.calendar


############# Merged Calendar #############


class MergedCalendar(CalendarMixin, EditableCalendarMixin):
    implements(ILaunchpadCalendar, ILaunchpadMergedCalendar)

    def __init__(self):
        self.id = None
        self.revision = 0
        self.owner = getUtility(ILaunchBag).user
        if self.owner is None:
            # The merged calendar can not be accessed when the user is
            # not logged in.  However this object still needs to be
            # instantiable when not logged in, so that the user gets
            # redirected to the login page when trying to access the
            # calendar, rather than seeing an error page.
            return
        self.subscriptions = ICalendarSubscriptionSubset(self.owner)
        self.title = _('Merged Calendar for %s') % self.owner.browsername

    def __iter__(self):
        for calendar in self.subscriptions:
            for event in calendar:
                yield event

    def expand(self, first, last):
        for calendar in self.subscriptions:
            for event in calendar.expand(first, last):
                yield event

    def addEvent(self, event):
        calendar = self.owner.getOrCreateCalendar()
        calendar.addEvent(event)

    def removeEvent(self, event):
        calendar = event.calendar
        calendar.removeEvent(event)


############# iCalendar export ###################

class ViewICalendar:
    """Publish an object implementing the ICalendar interface in
    the iCalendar format.  This allows desktop calendar clients to
    display the events."""
    __used_for__ = ICalendar

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        result = convert_calendar_to_ical(self.context)
        result = '\r\n'.join(result)

        self.request.response.setHeader('Content-Type', 'text/calendar')
        self.request.response.setHeader('Content-Length', len(result))

        return result
