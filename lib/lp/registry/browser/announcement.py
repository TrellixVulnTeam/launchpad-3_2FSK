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
    'AnnouncementView',
    ]

from zope.interface import implements, Interface
from zope.schema import Choice, TextLine

from canonical.cachedproperty import cachedproperty

from lp.registry.interfaces.announcement import IAnnouncement

from canonical.launchpad import _
from canonical.launchpad.browser.feeds import (
    AnnouncementsFeedLink, FeedsMixin, RootAnnouncementsFeedLink)
from canonical.launchpad.fields import AnnouncementDate, Summary, Title
from canonical.launchpad.interfaces.validation import valid_webref
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.launchpadform import (
    action, custom_widget, LaunchpadFormView)
from canonical.launchpad.webapp.menu import (
    ContextMenu, enabled_with_permission, Link, NavigationMenu)
from canonical.launchpad.webapp.publisher import canonical_url, LaunchpadView
from canonical.widgets import AnnouncementDateWidget


class AnnouncementMenuMixin:
    """A mixin of links common to many menus."""

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Modify announcement'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def retarget(self):
        text = 'Move announcement'
        return Link('+retarget', text, icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def publish(self):
        text = 'Publish announcement'
        enabled = not self.context.published
        return Link('+publish', text, icon='edit', enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def retract(self):
        text = 'Retract announcement'
        enabled = self.context.published
        return Link('+retract', text, icon='remove', enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def delete(self):
        text = 'Delete announcement'
        return Link('+delete', text, icon='trash-icon')

    @enabled_with_permission('launchpad.Edit')
    def announce(self):
        text = 'Make announcement'
        summary = 'Create an item of news for this project'
        return Link('+announce', text, summary, icon='add')


class AnnouncementContextMenu(ContextMenu, AnnouncementMenuMixin):
    """The menu for working with an Announcement."""
    usedfor = IAnnouncement
    links = ['edit', 'retarget', 'publish', 'retract', 'delete']


class IAnnouncementEditMenu(Interface):
    """A marker interface for modify announcement navigation menu."""


class AnnouncementEditNavigationMenu(NavigationMenu, AnnouncementMenuMixin):
    """A sub-menu for different aspects of modifying an announcement."""

    usedfor = IAnnouncementEditMenu
    facet = 'overview'
    title = 'Change announcement'
    links = ['edit', 'retarget', 'publish', 'retract', 'delete']

    def __init__(self, context):
        super(AnnouncementEditNavigationMenu, self).__init__(context)
        # Links always expect the context if be a model object, not a view.
        if isinstance(self.context, LaunchpadView):
            self.view = context
            self.context = context.context
        else:
            self.view = None
            self.context = context


class IAnnouncementCreateMenu(Interface):
    """A marker interface for creation announcement navigation menu."""


class AnnouncementCreateNavigationMenu(NavigationMenu, AnnouncementMenuMixin):
    """A sub-menu for different aspects of modifying an announcement."""

    usedfor = IAnnouncementCreateMenu
    facet = 'overview'
    title = 'Create announcement'
    links = ['announce']


class AnnouncementFormMixin:
    """A mixin to provide the common form features."""

    @property
    def page_title(self):
        """The html page title."""
        return self.label

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
        self.context.announce(
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
    implements(IAnnouncementEditMenu)

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
    """A view to move an annoucement to another project."""
    implements(IAnnouncementEditMenu)

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
    """A view to publish an annoucement."""
    implements(IAnnouncementEditMenu)

    schema = AddAnnouncementForm
    field_names = ['publication_date']
    label = _('Publish this announcement')

    custom_widget('publication_date', AnnouncementDateWidget)

    @action(_('Publish'), name='publish')
    def publish_action(self, action, data):
        publication_date = data['publication_date']
        self.context.setPublicationDate(publication_date)
        self.next_url = canonical_url(self.context.target)+'/+announcements'


class AnnouncementRetractView(AnnouncementFormMixin, LaunchpadFormView):
    """A view to unpublish an announcement."""
    implements(IAnnouncementEditMenu)

    schema = IAnnouncement
    label = _('Retract this announcement')

    @action(_('Retract'), name='retract')
    def retract_action(self, action, data):
        self.context.retract()
        self.next_url = canonical_url(self.context.target)+'/+announcements'


class AnnouncementDeleteView(AnnouncementFormMixin, LaunchpadFormView):
    """A view to delete an annoucement."""
    implements(IAnnouncementEditMenu)

    schema = IAnnouncement
    label = _('Delete this announcement')

    @action(_("Delete"), name="delete", validator='validate_cancel')
    def action_delete(self, action, data):
        self.context.destroySelf()
        self.next_url = canonical_url(self.context.target)+'/+announcements'


class HasAnnouncementsView(LaunchpadView, FeedsMixin):
    """A view class for pillars which have announcements."""
    implements(IAnnouncementCreateMenu)

    batch_size = 5

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
        return self.context.getAnnouncements(
                    limit=None, published_only=published_only)

    @cachedproperty
    def latest_announcements(self):
        published_only = not check_permission('launchpad.Edit', self.context)
        return self.context.getAnnouncements(
                    limit=5, published_only=published_only)

    @cachedproperty
    def show_announcements(self):
        return (self.latest_announcements.count() > 0
            or check_permission('launchpad.Edit', self.context))

    @cachedproperty
    def announcement_nav(self):
        return BatchNavigator(
            self.announcements, self.request,
            size=self.batch_size)


class AnnouncementSetView(HasAnnouncementsView):
    """View a list of announcements.

    All other feed links should be disabled on this page by
    overriding the feed_types class variable.
    """
    feed_types = (
        AnnouncementsFeedLink,
        RootAnnouncementsFeedLink,
        )


class AnnouncementView(LaunchpadView):
    """A view class for a single announcement."""
    implements(IAnnouncementEditMenu)
