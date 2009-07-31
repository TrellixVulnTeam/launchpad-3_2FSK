# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Announcement views."""

__metaclass__ = type

__all__ = [
    'AnnouncementAddView',
    'AnnouncementRetargetView',
    'AnnouncementPublishView',
    'AnnouncementRetractView',
    'AnnouncementDeleteView',
    'AnnouncementEditView',
    'AnnouncementContextMenu',
    'AnnouncementSetView',
    'HasAnnouncementsView',
    ]

from zope.interface import Interface

from zope.schema import Choice, TextLine

from canonical.cachedproperty import cachedproperty
from canonical.config import config

from lp.registry.interfaces.announcement import IAnnouncement
from canonical.launchpad import _
from canonical.launchpad.fields import AnnouncementDate, Summary, Title
from canonical.launchpad.interfaces.validation import valid_webref

from canonical.launchpad.webapp import (
    action, canonical_url, ContextMenu, custom_widget,
    enabled_with_permission, LaunchpadView, LaunchpadFormView, Link
    )
from canonical.launchpad.browser.feeds import (
    AnnouncementsFeedLink, FeedsMixin, RootAnnouncementsFeedLink)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.batching import BatchNavigator

from canonical.widgets import AnnouncementDateWidget


class AnnouncementContextMenu(ContextMenu):

    usedfor = IAnnouncement
    links = ['edit', 'retarget', 'retract']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Modify announcement'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def retarget(self):
        text = 'Move to another project'
        return Link('+retarget', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def retract(self):
        text = 'Retract announcement'
        return Link('+retract', text, icon='edit')


class AnnouncementFormMixin:
    """A mixin to provide the common form features."""

    @property
    def cancel_url(self):
        """The announcements URL."""
        return canonical_url(self.context.target, view_name='+announcements')


class AddAnnouncementForm(Interface):
    """Form definition for the view which creates new Announcements."""

    title = Title(title=_('Headline'), required=True)
    summary = Summary(title=_('Summary'), required=True)
    url = TextLine(title=_('URL'), required=False, constraint=valid_webref,
        description=_("The web location of your announcement."))
    publication_date = AnnouncementDate(title=_('Date'), required=True)


class AnnouncementAddView(LaunchpadFormView):
    """A view for creating a new Announcement."""

    schema = AddAnnouncementForm
    label = "Make an announcement"

    custom_widget('publication_date', AnnouncementDateWidget)

    @action(_('Make announcement'), name='announce')
    def announce_action(self, action, data):
        """Registers a new announcement."""
        announcement = self.context.announce(
            user = self.user,
            title = data.get('title'),
            summary = data.get('summary'),
            url = data.get('url'),
            publication_date = data.get('publication_date')
            )
        self.next_url = canonical_url(self.context)

    @property
    def action_url(self):
        return "%s/+announce" % canonical_url(self.context)

    @property
    def cancel_url(self):
        """The project's URL."""
        return canonical_url(self.context)


class AnnouncementEditView(AnnouncementFormMixin, LaunchpadFormView):
    """A view which allows you to edit the announcement."""

    schema = AddAnnouncementForm
    field_names = ['title', 'summary', 'url', ]
    label = _('Modify this announcement')

    @property
    def initial_values(self):
        return {
            'title': self.context.title,
            'summary': self.context.summary,
            'url': self.context.url,
            }

    @action(_('Modify'), name='modify')
    def modify_action(self, action, data):
        self.context.modify(title=data.get('title'),
                            summary=data.get('summary'),
                            url=data.get('url'))
        self.next_url = canonical_url(self.context.target)+'/+announcements'


class AnnouncementRetargetForm(Interface):
    """Form that requires the user to choose a pillar for the Announcement."""

    target = Choice(
        title=_("For"),
        description=_("The project where this announcement is being made."),
        required=True, vocabulary='DistributionOrProductOrProject')


class AnnouncementRetargetView(AnnouncementFormMixin, LaunchpadFormView):

    schema = AnnouncementRetargetForm
    field_names = ['target']
    label = _('Move this announcement to a different project')

    def validate(self, data):
        """Ensure that the person can publish announcement at the new
        target.
        """

        target = data.get('target')

        if target is None:
            self.setFieldError('target',
                "There is no project with the name '%s'. "
                "Please check that name and try again." %
                self.request.form.get("field.target"))
            return

        if not check_permission('launchpad.Edit', target):
            self.setFieldError('target',
                "You don't have permission to make announcements for "
                "%s. Please check that name and try again." %
                target.displayname)
            return

    @action(_('Retarget'), name='retarget')
    def retarget_action(self, action, data):
        target = data.get('target')
        self.context.retarget(target)
        self.next_url = canonical_url(self.context.target)+'/+announcements'


class AnnouncementPublishView(AnnouncementFormMixin, LaunchpadFormView):

    schema = AddAnnouncementForm
    field_names = ['publication_date']
    label = _('Publish this announcement')

    custom_widget('publication_date', AnnouncementDateWidget)

    @action(_('Publish'), name='publish')
    def publish_action(self, action, data):
        publication_date = data['publication_date']
        self.context.set_publication_date(publication_date)
        self.next_url = canonical_url(self.context.target)+'/+announcements'


class AnnouncementRetractView(AnnouncementFormMixin, LaunchpadFormView):

    schema = IAnnouncement
    label = _('Retract this announcement')

    @action(_('Retract'), name='retract')
    def retract_action(self, action, data):
        self.context.retract()
        self.next_url = canonical_url(self.context.target)+'/+announcements'


class AnnouncementDeleteView(AnnouncementFormMixin, LaunchpadFormView):

    schema = IAnnouncement
    label = _('Delete this announcement')

    @action(_("Delete"), name="delete", validator='validate_cancel')
    def action_delete(self, action, data):
        self.context.destroySelf()
        self.next_url = canonical_url(self.context.target)+'/+announcements'


class HasAnnouncementsView(LaunchpadView, FeedsMixin):
    """A view class for pillars which have announcements."""

    @cachedproperty
    def feed_url(self):
        if AnnouncementsFeedLink.usedfor.providedBy(self.context):
            return AnnouncementsFeedLink(self.context).href
        elif RootAnnouncementsFeedLink.usedfor.providedBy(self.context):
            return RootAnnouncementsFeedLink(self.context).href
        else:
            raise AssertionError, 'Unknown feed source'

    @cachedproperty
    def announcements(self):
        published_only = not check_permission('launchpad.Edit', self.context)
        return self.context.announcements(
                    limit=None, published_only=published_only)

    @cachedproperty
    def latest_announcements(self):
        published_only = not check_permission('launchpad.Edit', self.context)
        return self.context.announcements(
                    limit=5, published_only=published_only)

    @cachedproperty
    def announcement_nav(self):
        return BatchNavigator(
            self.announcements, self.request,
            size=config.launchpad.default_batch_size)


class AnnouncementSetView(HasAnnouncementsView):
    """View a list of announcements.

    All other feed links should be disabled on this page by
    overriding the feed_types class variable.
    """
    feed_types = (
        AnnouncementsFeedLink,
        RootAnnouncementsFeedLink,
        )
