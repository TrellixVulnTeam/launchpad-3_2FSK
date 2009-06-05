# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""Milestone views."""

__metaclass__ = type

__all__ = [
    'MilestoneAddView',
    'MilestoneContextMenu',
    'MilestoneDeleteView',
    'MilestoneEditView',
    'MilestoneNavigation',
    'MilestoneOverviewNavigationMenu',
    'MilestoneSetNavigation',
    ]

from zope.component import getUtility
from zope.formlib import form
from zope.schema import Choice

from canonical.cachedproperty import cachedproperty
from canonical.launchpad import _
from canonical.launchpad.browser.bugtask import BugTaskListingItem
from canonical.launchpad.interfaces.bugtask import (
    BugTaskSearchParams, IBugTaskSet)
from lp.registry.interfaces.milestone import (
    IMilestone, IMilestoneSet, IProjectMilestone)
from canonical.launchpad.webapp import (
    action, canonical_url, custom_widget, ContextMenu, Link,
    LaunchpadEditFormView, LaunchpadFormView, LaunchpadView,
    enabled_with_permission, GetitemNavigation, Navigation, NavigationMenu)
from canonical.launchpad.webapp.interfaces import ILaunchBag
from canonical.widgets import DateWidget

from lp.registry.browser import RegistryDeleteViewMixin
from lp.registry.browser.product import ProductDownloadFileMixin


class MilestoneSetNavigation(GetitemNavigation):

    usedfor = IMilestoneSet


# XXX: jamesh 2005-12-14:
# This class is required in order to make use of a side effect of
# Navigation.publishTraverse: adding context objects to
# request.traversed_objects.
class MilestoneNavigation(Navigation):

    usedfor = IMilestone


class MilestoneContextMenu(ContextMenu):

    usedfor = IMilestone

    links = ['edit', 'subscribe', 'create_release', 'view_release']

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        text = 'Change details'
        # ProjectMilestones are virtual milestones and do not have
        # any properties which can be edited.
        enabled = not IProjectMilestone.providedBy(self.context)
        summary = "Edit this milestone"
        return Link(
            '+edit', text, icon='edit', summary=summary, enabled=enabled)

    def subscribe(self):
        enabled = not IProjectMilestone.providedBy(self.context)
        return Link('+subscribe', 'Subscribe to bug mail',
                    icon='edit', enabled=enabled)

    @enabled_with_permission('launchpad.Edit')
    def create_release(self):
        text = 'Create release'
        # Releases only exist for products.
        # A milestone can only have a single product release.
        enabled = (not IProjectMilestone.providedBy(self.context)
                   and self.context.product_release is None)
        return Link('+addrelease', text, icon='add', enabled=enabled)

    def view_release(self):
        text = 'View release'
        # Releases only exist for products.
        if (not IProjectMilestone.providedBy(self.context)
            and self.context.product_release is not None):
            enabled = True
            url = canonical_url(self.context.product_release)
        else:
            enabled = False
            url = '.'
        return Link(url, text, enabled=enabled)


class MilestoneOverviewNavigationMenu(NavigationMenu):
    """Overview navigation menus for `IProductSeries` objects."""
    # Suppress the ProductOverviewNavigationMenu from showing on milestones,
    # pages.
    usedfor = IMilestone
    facet = 'overview'
    links = ()


class MilestoneView(LaunchpadView, ProductDownloadFileMixin):
    """A View for listing milestones and releases."""
    # XXX sinzui 2009-05-29 bug=381672: Extract the BugTaskListingItem rules
    # to a mixin so that MilestoneView and others can use it.

    def __init__(self, context, request):
        """See `LaunchpadView`.

        This view may be used with a milestone or a release. The milestone
        and release (if it exists) are accessible are attributes. The context
        attribute will always be the milestone.

        :param context: `IMilestone` or `IProductRelease`.
        :param request: `ILaunchpadRequest`.
        """
        super(MilestoneView, self).__init__(context, request)
        if IMilestone.providedBy(context):
            self.milestone = context
            self.release = context.product_release
        else:
            self.milestone = context.milestone
            self.release = context
        self.context = self.milestone

    def initialize(self):
        """See `LaunchpadView`."""
        self.form = self.request.form
        self.processDeleteFiles()

    def getReleases(self):
        """See `ProductDownloadFileMixin`."""
        return set([self.release])

    @cachedproperty
    def download_files(self):
        """The release's files as DownloadFiles."""
        if self.release is None or self.release.files.count() == 0:
            return None
        return [self.getDownloadFile(file_, self.release)
                for file_ in self.release.files]

    # Listify and cache the specifications and bugtasks to avoid making
    # the same query over and over again when evaluating in the template.
    @cachedproperty
    def specifications(self):
        """The list of specifications targeted to this milestone."""
        return list(self.context.specifications)

    @cachedproperty
    def _bugtasks(self):
        """The list of non-conjoined bugtasks targeted to this milestone."""
        user = getUtility(ILaunchBag).user
        params = BugTaskSearchParams(user, milestone=self.context,
                    orderby=['-importance', 'datecreated', 'id'],
                    omit_dupes=True)
        tasks = getUtility(IBugTaskSet).search(params)
        # We could replace all the code below with a simple
        # >>> [task for task in tasks if task.conjoined_master is None]
        # But that'd cause one extra hit to the DB for every bugtask returned
        # by the search above, so we do a single query to get all of a task's
        # siblings here and use that to find whether or not a given bugtask
        # has a conjoined master.
        bugs_and_tasks = getUtility(IBugTaskSet).getBugTasks(
            [task.bug.id for task in tasks])
        non_conjoined_slaves = []
        for task in tasks:
            if task.getConjoinedMaster(bugs_and_tasks[task.bug]) is None:
                non_conjoined_slaves.append(task)
        return non_conjoined_slaves

    @cachedproperty
    def _bug_badge_properties(self):
        """The badges for each bug associates with this milestone."""
        return getUtility(IBugTaskSet).getBugTaskBadgeProperties(
            self._bugtasks)

    def _getListingItem(self, bugtask):
        """Return a decorated bugtask for the bug listing."""
        badge_property = self._bug_badge_properties[bugtask]
        return BugTaskListingItem(
            bugtask,
            badge_property['has_mentoring_offer'],
            badge_property['has_branch'],
            badge_property['has_specification'])

    @cachedproperty
    def bugtasks(self):
        """The list of bugtasks targeted to this milestone for listing."""
        return [self._getListingItem(bugtask) for bugtask in self._bugtasks]

    @property
    def bugtask_count_text(self):
        """The formatted count of bugs for this milestone."""
        count = len(self.bugtasks)
        if count == 1:
            return '<strong>1 bug</strong>'
        else:
            return '<strong>%d bugs</strong>' % count

    @property
    def specification_count_text(self):
        """The formatted count of specifications for this milestone."""
        count = len(self.specifications)
        if count == 1:
            return '<strong>1 blueprint</strong>'
        else:
            return '<strong>%d blueprints</strong>' % count

    @property
    def is_project_milestone(self):
        """Check, if the current milestone is a project milestone.

        Return true, if the current milestone is a project milestone,
        else return False."""
        return IProjectMilestone.providedBy(self.context)

    @property
    def has_bugs_or_specs(self):
        """Does the milestone have any bugtasks and specifications?"""
        return len(self.bugtasks) > 0  or len(self.specifications) > 0


class MilestoneAddView(LaunchpadFormView):
    """A view for creating a new Milestone."""

    schema = IMilestone
    field_names = ['name', 'code_name', 'dateexpected', 'summary']
    label = "Register a new milestone"

    custom_widget('dateexpected', DateWidget)

    @action(_('Register Milestone'), name='register')
    def register_action(self, action, data):
        """Use the newMilestone method on the context to make a milestone."""
        milestone = self.context.newMilestone(
            name=data.get('name'),
            code_name=data.get('code_name'),
            dateexpected=data.get('dateexpected'),
            summary=data.get('summary'))
        self.next_url = canonical_url(self.context)

    @property
    def action_url(self):
        return "%s/+addmilestone" % canonical_url(self.context)

    @property
    def cancel_url(self):
        return canonical_url(self.context)


class MilestoneEditView(LaunchpadEditFormView):
    """A view for editing milestone properties.

    This view supports editing of properties such as the name, the date it is
    expected to complete, the milestone description, and whether or not it is
    active.
    """

    schema = IMilestone
    label = "Modify milestone details"

    custom_widget('dateexpected', DateWidget)

    @property
    def cancel_url(self):
        """The context's URL."""
        return canonical_url(self.context)

    @property
    def field_names(self):
        """See `LaunchpadFormView`.

        There are two series fields, one for for product milestones and the
        other for distribution milestones. The product milestone may change
        its productseries. The distribution milestone may change its
        distroseries.
        """
        names = ['name', 'code_name', 'active', 'dateexpected', 'summary']
        if self.context.product is None:
            # This is a distribution milestone.
            names.append('distroseries')
        else:
            names.append('productseries')
        return names

    def setUpFields(self):
        """See `LaunchpadFormView`.

        The schema permits the series field to be None (required=False) to
        create the milestone, but once a series field is set, None is invalid.
        The choice for the series is redefined to ensure None is not included.
        """
        super(MilestoneEditView, self).setUpFields()
        if self.context.product is None:
            # This is a distribution milestone.
            choice = Choice(
                __name__='distroseries', vocabulary="FilteredDistroSeries")
        else:
            choice = Choice(
                __name__='productseries', vocabulary="FilteredProductSeries")
        choice.title = _("Series")
        choice.description = _("The series for which this is a milestone.")
        field = form.Fields(choice, render_context=self.render_context)
        # Remove the schema's field, then add back the replacement field.
        self.form_fields = self.form_fields.omit(choice.__name__) + field

    @action(_('Update'), name='update')
    def update_action(self, action, data):
        self.updateContextFromData(data)
        self.next_url = canonical_url(self.context)


class MilestoneDeleteView(LaunchpadFormView, RegistryDeleteViewMixin):
    """A view for deleting an `IMilestone`."""
    schema = IMilestone
    field_names = []

    @property
    def label(self):
        """The form label."""
        return 'Delete %s' % self.context.title

    @cachedproperty
    def bugtasks(self):
        """The list `IBugTask`s targeted to the milestone."""
        return self._getBugtasks(self.context)

    @cachedproperty
    def specifications(self):
        """The list `ISpecification`s targeted to the milestone."""
        return self._getSpecifications(self.context)

    @cachedproperty
    def product_release(self):
        """The `IProductRelease` associated with the milestone."""
        return self._getProductRelease(self.context)

    @cachedproperty
    def product_release_files(self):
        """The list of `IProductReleaseFile`s related to the milestone."""
        return self._getProductReleaseFiles(self.context)

    @action('Delete this Milestone', name='delete')
    def delete_action(self, action, data):
        # Any associated bugtasks and specifications are untargeted.
        series = self.context.productseries
        name = self.context.name
        self._deleteMilestone(self.context)
        self.request.response.addInfoNotification(
            "Milestone %s deleted." % name)
        self.next_url = canonical_url(series)


