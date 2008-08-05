# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Sprint views."""

__metaclass__ = type
__all__ = [
    'SprintAddView',
    'SprintAttendeesCsvExportView',
    'SprintBrandingView',
    'SprintEditView',
    'SprintFacets',
    'SprintMeetingExportView',
    'SprintNavigation',
    'SprintOverviewMenu',
    'SprintSetContextMenu',
    'SprintSetFacets',
    'SprintSetNavigation',
    'SprintSetSOP',
    'SprintSetView',
    'SprintSpecificationsMenu',
    'SprintTopicSetView',
    'SprintView',
    ]

import csv
import pytz
from StringIO import StringIO

from zope.component import getUtility
from zope.app.form.browser import TextAreaWidget

from canonical.launchpad import _
from canonical.cachedproperty import cachedproperty
from canonical.launchpad.browser.branding import BrandingChangeView
from canonical.launchpad.browser.specificationtarget import (
    HasSpecificationsView)
from canonical.launchpad.interfaces import (
    ISprint, ISprintSet, SpecificationDefinitionStatus, SpecificationFilter,
    SpecificationPriority, SpecificationSort)
from canonical.launchpad.webapp import (
    ApplicationMenu, ContextMenu, GetitemNavigation, LaunchpadEditFormView,
    LaunchpadFormView, LaunchpadView, Link, Navigation,
    StandardLaunchpadFacets, action, canonical_url, custom_widget,
    enabled_with_permission)
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.browser.launchpad import (
    StructuralObjectPresentation)
from canonical.widgets.date import DateTimeWidget


class SprintFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an ISprint."""

    usedfor = ISprint
    enable_only = ['overview', 'specifications']

    def specifications(self):
        text = 'Blueprints'
        summary = 'Topics for discussion at %s' % self.context.title
        return Link('', text, summary)


class SprintNavigation(Navigation):

    usedfor = ISprint

    def breadcrumb(self):
        return self.context.title


class SprintOverviewMenu(ApplicationMenu):

    usedfor = ISprint
    facet = 'overview'
    links = ['attendance', 'registration', 'attendee_export', 'edit',
             'branding']

    def attendance(self):
        text = 'Register yourself'
        summary = 'Register as an attendee of the meeting'
        return Link('+attend', text, summary, icon='add')

    def registration(self):
        text = 'Register someone else'
        summary = 'Register someone else to attend the meeting'
        return Link('+register', text, summary, icon='add')

    @enabled_with_permission('launchpad.View')
    def attendee_export(self):
        text = 'Export attendees to CSV'
        summary = 'Export attendee contact information to CSV format'
        return Link('+attendees-csv', text, summary, icon='info')

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Change details'
        summary = 'Modify the meeting description, dates or title'
        return Link('+edit', text, summary, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def branding(self):
        text = 'Change branding'
        summary = 'Modify the imagery used to represent this meeting'
        return Link('+branding', text, summary, icon='edit')


class SprintSpecificationsMenu(ApplicationMenu):

    usedfor = ISprint
    facet = 'specifications'
    links = ['assignments', 'declined', 'settopics', 'roadmap', 'addspec']

    def assignments(self):
        text = 'Assignments'
        summary = 'View the specification assignments'
        return Link('+assignments', text, summary, icon='info')

    def declined(self):
        text = 'List declined blueprints'
        summary = 'Show topics that were not accepted for discussion'
        return Link('+specs?acceptance=declined', text, summary, icon='info')

    @enabled_with_permission('launchpad.Driver')
    def settopics(self):
        text = 'Set agenda'
        summary = 'Approve or defer topics for discussion'
        return Link('+settopics', text, summary, icon='edit')

    def roadmap(self):
        text = 'Roadmap'
        summary = 'Suggest a sequence of implementation for these features'
        return Link('+roadmap', text, summary, icon='info')

    def addspec(self):
        text = 'Register a blueprint'
        summary = 'Register a new blueprint for this meeting'
        return Link('+addspec', text, summary, icon='info')


class SprintSetNavigation(GetitemNavigation):

    usedfor = ISprintSet

    def breadcrumb(self):
        return 'Meetings'


class SprintSetFacets(StandardLaunchpadFacets):
    """The facet menu for an ISprintSet."""

    usedfor = ISprintSet
    enable_only = ['overview', ]


class SprintSetSOP(StructuralObjectPresentation):

    def getIntroHeading(self):
        return None

    def getMainHeading(self):
        return 'Meetings and Sprints'

    def listChildren(self, num):
        return []

    def listAltChildren(self, num):
        return None


class SprintSetContextMenu(ContextMenu):

    usedfor = ISprintSet
    links = ['products', 'distributions', 'people', 'sprints', 'all', 'new']

    def all(self):
        text = 'List all meetings'
        return Link('+all', text)

    def new(self):
        text = 'Register a meeting'
        return Link('+new', text, icon='add')

    def products(self):
        return Link('/projects/', 'View projects')

    def distributions(self):
        return Link('/distros/', 'View distributions')

    def people(self):
        return Link('/people/', 'View people')

    def sprints(self):
        return Link('/sprints/', 'View meetings')


class SprintView(HasSpecificationsView, LaunchpadView):

    __used_for__ = ISprint

    def initialize(self):
        self.notices = []
        self.latest_specs_limit = 5
        self.tzinfo = pytz.timezone(self.context.time_zone)

    def attendance(self):
        """establish if this user is attending"""
        if self.user is None:
            return None
        for subscription in self.context.subscriptions:
            if subscription.person.id == self.user.id:
                return subscription
        return None

    @cachedproperty
    def spec_links(self):
        """List all of the SprintSpecifications appropriate for this view."""
        filter = self.spec_filter
        return shortlist(self.context.specificationLinks(filter=filter))

    @cachedproperty
    def count(self):
        return len(self.spec_links)

    @cachedproperty
    def proposed_count(self):
        filter = [SpecificationFilter.PROPOSED]
        return self.context.specificationLinks(filter=filter).count()

    @cachedproperty
    def latest_approved(self):
        filter = [SpecificationFilter.ACCEPTED]
        return self.context.specifications(filter=filter,
                    quantity=self.latest_specs_limit,
                    sort=SpecificationSort.DATE)

    def formatDateTime(self, dt):
        """Format a datetime value according to the sprint's time zone"""
        dt = dt.astimezone(self.tzinfo)
        return dt.strftime('%Y-%m-%d %H:%M %Z')

    def formatDate(self, dt):
        """Format a date value according to the sprint's time zone"""
        dt = dt.astimezone(self.tzinfo)
        return dt.strftime('%Y-%m-%d')

    _local_timeformat = '%H:%M on %A, %Y-%m-%d'
    @property
    def local_start(self):
        """The sprint start time, in the local time zone, as text."""
        tz = pytz.timezone(self.context.time_zone)
        return self.context.time_starts.astimezone(tz).strftime(
                    self._local_timeformat)

    @property
    def local_end(self):
        """The sprint end time, in the local time zone, as text."""
        tz = pytz.timezone(self.context.time_zone)
        return self.context.time_ends.astimezone(tz).strftime(
                    self._local_timeformat)


class SprintAddView(LaunchpadFormView):
    """Form for creating sprints"""

    schema = ISprint
    label = "Register a meeting"
    field_names = ['name', 'title', 'summary', 'home_page', 'driver',
                   'time_zone', 'time_starts', 'time_ends', 'address',
                   ]
    custom_widget('summary', TextAreaWidget, height=5)
    custom_widget('time_starts', DateTimeWidget, display_zone=False)
    custom_widget('time_ends', DateTimeWidget, display_zone=False)
    custom_widget('address', TextAreaWidget, height=3)

    sprint = None

    def setUpWidgets(self):
        LaunchpadFormView.setUpWidgets(self)
        timeformat = '%Y-%m-%d %H:%M'
        self.widgets['time_starts'].timeformat = timeformat
        self.widgets['time_ends'].timeformat = timeformat
        time_zone_widget = self.widgets['time_zone']
        if time_zone_widget.hasValidInput():
            tz = pytz.timezone(time_zone_widget.getInputValue())
            self.widgets['time_starts'].required_time_zone = tz
            self.widgets['time_ends'].required_time_zone = tz

    def validate(self, data):
        time_starts = data.get('time_starts')
        time_ends = data.get('time_ends')
        if time_starts and time_ends and time_ends < time_starts:
            self.setFieldError(
                'time_ends', "This event can't start after it ends")

    @action(_('Add Sprint'), name='add')
    def add_action(self, action, data):
        self.sprint = getUtility(ISprintSet).new(
            owner=self.user,
            name=data['name'],
            title=data['title'],
            summary=data['summary'],
            home_page=data['home_page'],
            driver=data['driver'],
            time_zone=data['time_zone'],
            time_starts=data['time_starts'],
            time_ends=data['time_ends'],
            address=data['address'],
            )
        self.request.response.addInfoNotification('Sprint created.')

    @property
    def next_url(self):
        assert self.sprint is not None, 'No sprint has been created'
        return canonical_url(self.sprint)


class SprintBrandingView(BrandingChangeView):

    schema = ISprint
    # sabdfl 2007-03-28 deliberately leaving icon off the list, i think it
    # would be overkill, we can add it later if people ask for it
    field_names = ['logo', 'mugshot']


class SprintEditView(LaunchpadEditFormView):
    """Form for editing sprints"""

    schema = ISprint
    label = "Edit sprint details"
    field_names = ['name', 'title', 'summary', 'home_page', 'driver',
                   'time_zone', 'time_starts', 'time_ends', 'address',
                   ]
    custom_widget('summary', TextAreaWidget, height=5)
    custom_widget('time_starts', DateTimeWidget, display_zone=False)
    custom_widget('time_ends', DateTimeWidget, display_zone=False)
    custom_widget('address', TextAreaWidget, height=3)

    def setUpWidgets(self):
        LaunchpadEditFormView.setUpWidgets(self)
        timeformat = '%Y-%m-%d %H:%M'
        self.widgets['time_starts'].timeformat = timeformat
        self.widgets['time_ends'].timeformat = timeformat
        time_zone_widget = self.widgets['time_zone']
        # What time zone are the start and end values relative to?
        if time_zone_widget.hasValidInput():
            tz = pytz.timezone(time_zone_widget.getInputValue())
        else:
            tz = pytz.timezone(self.context.time_zone)
        self.widgets['time_starts'].required_time_zone = tz
        self.widgets['time_ends'].required_time_zone = tz

    def validate(self, data):
        time_starts = data.get('time_starts')
        time_ends = data.get('time_ends')
        if time_starts and time_ends and time_ends < time_starts:
            self.setFieldError(
                'time_ends', "This event can't start after it ends")

    @action(_('Change'), name='change')
    def change_action(self, action, data):
        self.updateContextFromData(data)

    @property
    def next_url(self):
        return canonical_url(self.context)


class SprintTopicSetView(HasSpecificationsView, LaunchpadView):
    """Custom view class to process the results of this unusual page.

    It is unusual because we want to display multiple objects with
    checkboxes, then process the selected items, which is not the usual
    add/edit metaphor."""

    def initialize(self):
        self.status_message = None
        self.process_form()
        self.attendee_ids = set(
            attendance.attendee.id for attendance in self.context.attendances)


    @cachedproperty
    def spec_filter(self):
        """Return the specification links with PROPOSED status for this
        sprint.
        """
        return [SpecificationFilter.PROPOSED]

    @cachedproperty
    def spec_links(self):
        filter = self.spec_filter
        return self.context.specificationLinks(filter=filter)

    def process_form(self):
        """Largely copied from webapp/generalform.py, without the
        schema processing bits because we are not rendering the form in the
        usual way. Instead, we are creating our own form in the page
        template and interpreting it here.
        """
        form = self.request.form

        if 'SUBMIT_CANCEL' in form:
            self.status_message = 'Cancelled'
            self.request.response.redirect(
                canonical_url(self.context)+'/+specs')
            return

        if 'SUBMIT_ACCEPT' not in form and 'SUBMIT_DECLINE' not in form:
            self.status_message = ''
            return

        if self.request.method == 'POST':
            if 'speclink' not in form:
                self.status_message = (
                    'Please select specifications to accept or decline.')
                return
            # determine if we are accepting or declining
            if 'SUBMIT_ACCEPT' in form:
                assert 'SUBMIT_DECLINE' not in form
                action = 'Accepted'
            else:
                assert 'SUBMIT_DECLINE' in form
                action = 'Declined'

        selected_specs = form['speclink']
        if isinstance(selected_specs, unicode):
            # only a single item was selected, but we want to deal with a
            # list for the general case, so convert it to a list
            selected_specs = [selected_specs]

        if action == 'Accepted':
            action_fn = self.context.acceptSpecificationLinks
        else:
            action_fn = self.context.declineSpecificationLinks
        leftover = action_fn(selected_specs, self.user)

        # Status message like: "Accepted 27 specification(s)."
        self.status_message = '%s %d specification(s).' % (
            action, len(selected_specs))

        if leftover == 0:
            # they are all done, so redirect back to the spec listing page
            self.request.response.redirect(
                canonical_url(self.context)+'/+specs')


class SprintMeetingExportView(LaunchpadView):
    """View to provide information used the sprint meeting XML export view."""

    def initialize(self):
        self.attendees = []
        attendee_set = set()
        for attendance in self.context.attendances:
            self.attendees.append(dict(
                name=attendance.attendee.name,
                displayname=attendance.attendee.displayname,
                start=attendance.time_starts.strftime('%Y-%m-%dT%H:%M:%SZ'),
                end=attendance.time_ends.strftime('%Y-%m-%dT%H:%M:%SZ')))
            attendee_set.add(attendance.attendee)

        self.specifications = []
        for speclink in self.context.specificationLinks(
            filter=[SpecificationFilter.ACCEPTED]):
            spec = speclink.specification

            # skip sprints with no priority or less than low:
            if (spec.priority is None or
                spec.priority < SpecificationPriority.UNDEFINED):
                continue

            if (spec.definition_status not in
                [SpecificationDefinitionStatus.NEW,
                 SpecificationDefinitionStatus.DISCUSSION,
                 SpecificationDefinitionStatus.DRAFT]):
                continue

            # get the list of attendees that will attend the sprint
            is_required = dict((sub.person, sub.essential)
                               for sub in spec.subscriptions)
            interested = set(is_required.keys()).intersection(attendee_set)
            if spec.assignee is not None:
                interested.add(spec.assignee)
                is_required[spec.assignee] = True
            if spec.drafter is not None:
                interested.add(spec.drafter)
                is_required[spec.drafter] = True
            interested = [dict(name=person.name,
                               required=is_required[person])
                          for person in interested]

            self.specifications.append(dict(
                spec=spec,
                interested=interested))

    def render(self):
        self.request.response.setHeader('content-type',
                                        'application/xml;charset=utf-8')
        body = LaunchpadView.render(self)
        return body.encode('utf-8')


class SprintSetView(LaunchpadView):

    def all_batched(self):
        return BatchNavigator(self.context.all, self.request)


class SprintAttendeesCsvExportView(LaunchpadView):
    """View for exporting the attendees for a sprint as CSV."""

    def encode_value(self, value):
        """Encode a value for CSV.

        Return the string representation of `value` encoded as UTF-8,
        or the empty string if value is None."""
        if value is not None:
            return unicode(value).encode('utf-8')
        else:
            return ''

    def render(self):
        """Render a CSV output of all the attendees for a sprint."""
        rows = [('Launchpad username',
                 'Display name',
                 'Email',
                 'IRC nickname',
                 'Phone',
                 'Organization',
                 'City',
                 'Country',
                 'Timezone',
                 'Arriving',
                 'Leaving')]
        for attendance in self.context.attendances:
            irc_nicknames = ', '.join(sorted(set(
                [ircid.nickname for ircid
                 in attendance.attendee.ircnicknames])))
            if attendance.attendee.country is None:
                country = ''
            else:
                country = attendance.attendee.country.name
            rows.append(
                (attendance.attendee.name,
                 attendance.attendee.displayname,
                 attendance.attendee.safe_email_or_blank,
                 irc_nicknames,
                 attendance.attendee.phone,
                 attendance.attendee.organization,
                 attendance.attendee.city,
                 country,
                 attendance.attendee.time_zone,
                 attendance.time_starts.strftime('%Y-%m-%dT%H:%M:%SZ'),
                 attendance.time_ends.strftime('%Y-%m-%dT%H:%M:%SZ')))
        # CSV can't handle unicode, so we force encoding
        # everything as UTF-8
        rows = [[self.encode_value(column)
                 for column in row]
                for row in rows]
        self.request.response.setHeader('Content-type', 'text/csv')
        self.request.response.setHeader(
            'Content-disposition',
            'attachment; filename=%s-attendees.csv' % self.context.name)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerows(rows)
        return output.getvalue()
