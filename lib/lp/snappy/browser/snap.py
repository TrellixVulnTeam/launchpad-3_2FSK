# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snap views."""

__metaclass__ = type
__all__ = [
    'SnapAddView',
    'SnapDeleteView',
    'SnapEditView',
    'SnapNavigation',
    'SnapNavigationMenu',
    'SnapView',
    ]

from lazr.restful.interface import (
    copy_field,
    use_template,
    )
from zope.component import getUtility
from zope.interface import Interface
from zope.schema import Choice

from lp.app.browser.launchpadform import (
    action,
    custom_widget,
    LaunchpadEditFormView,
    LaunchpadFormView,
    render_radio_widget_part,
    )
from lp.app.browser.lazrjs import InlinePersonEditPickerWidget
from lp.app.browser.tales import format_link
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.app.widgets.itemswidgets import LaunchpadRadioWidget
from lp.code.browser.widgets.gitref import GitRefWidget
from lp.code.interfaces.gitref import IGitRef
from lp.registry.enums import VCSType
from lp.services.features import getFeatureFlag
from lp.services.webapp import (
    canonical_url,
    enabled_with_permission,
    LaunchpadView,
    Link,
    Navigation,
    NavigationMenu,
    stepthrough,
    )
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.breadcrumb import (
    Breadcrumb,
    NameBreadcrumb,
    )
from lp.snappy.interfaces.snap import (
    ISnap,
    ISnapSet,
    SNAP_FEATURE_FLAG,
    SnapFeatureDisabled,
    NoSuchSnap,
    )
from lp.snappy.interfaces.snapbuild import ISnapBuildSet
from lp.soyuz.browser.build import get_build_by_id_str


class SnapNavigation(Navigation):
    usedfor = ISnap

    @stepthrough('+build')
    def traverse_build(self, name):
        build = get_build_by_id_str(ISnapBuildSet, name)
        if build is None or build.snap != self.context:
            return None
        return build


class SnapBreadcrumb(NameBreadcrumb):

    @property
    def inside(self):
        return Breadcrumb(
            self.context.owner,
            url=canonical_url(self.context.owner, view_name="+snap"),
            text="Snap packages", inside=self.context.owner)


class SnapNavigationMenu(NavigationMenu):
    """Navigation menu for snap packages."""

    usedfor = ISnap

    facet = 'overview'

    links = ('edit', 'delete', 'admin')

    @enabled_with_permission('launchpad.Admin')
    def admin(self):
        return Link('+admin', 'Administer snap package', icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        return Link('+edit', 'Edit snap package', icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def delete(self):
        return Link('+delete', 'Delete snap package', icon='trash-icon')


class SnapView(LaunchpadView):
    """Default view of a Snap."""

    @property
    def builds(self):
        return builds_for_snap(self.context)

    @property
    def person_picker(self):
        field = copy_field(
            ISnap['owner'],
            vocabularyName='UserTeamsParticipationPlusSelfSimpleDisplay')
        return InlinePersonEditPickerWidget(
            self.context, field, format_link(self.context.owner),
            header='Change owner', step_title='Select a new owner')


def builds_for_snap(snap):
    """A list of interesting builds.

    All pending builds are shown, as well as 1-10 recent builds.  Recent
    builds are ordered by date finished (if completed) or date_started (if
    date finished is not set due to an error building or other circumstance
    which resulted in the build not being completed).  This allows started
    but unfinished builds to show up in the view but be discarded as more
    recent builds become available.

    Builds that the user does not have permission to see are excluded.
    """
    builds = [
        build for build in snap.pending_builds
        if check_permission('launchpad.View', build)]
    for build in snap.completed_builds:
        if not check_permission('launchpad.View', build):
            continue
        builds.append(build)
        if len(builds) >= 10:
            break
    return builds


class ISnapEditSchema(Interface):
    """Schema for adding or editing a snap package."""

    use_template(ISnap, include=[
        'owner',
        'name',
        'require_virtualized',
        ])
    distro_series = Choice(
        vocabulary='BuildableDistroSeries', title=u'Distribution series')
    vcs = Choice(vocabulary=VCSType, required=True, title=u'VCS')

    # Each of these is only required if vcs has an appropriate value.  Later
    # validation takes care of adjusting the required attribute.
    branch = copy_field(ISnap['branch'], required=True)
    git_ref = copy_field(ISnap['git_ref'], required=True)


class SnapAddView(LaunchpadFormView):
    """View for creating snap packages."""

    page_title = label = 'Create a new snap package'

    schema = ISnapEditSchema
    field_names = ['owner', 'name', 'distro_series']
    custom_widget('distro_series', LaunchpadRadioWidget)

    def initialize(self):
        """See `LaunchpadView`."""
        if not getFeatureFlag(SNAP_FEATURE_FLAG):
            raise SnapFeatureDisabled
        super(SnapAddView, self).initialize()

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    @property
    def initial_values(self):
        # XXX cjwatson 2015-09-18: Hack to ensure that we don't end up
        # accidentally selecting ubuntu-rtm/14.09 or similar.
        # ubuntu.currentseries will always be in BuildableDistroSeries.
        series = getUtility(ILaunchpadCelebrities).ubuntu.currentseries
        return {
            'owner': self.user,
            'distro_series': series,
            }

    @action('Create snap package', name='create')
    def request_action(self, action, data):
        if IGitRef.providedBy(self.context):
            kwargs = {'git_ref': self.context}
        else:
            kwargs = {'branch': self.context}
        snap = getUtility(ISnapSet).new(
            self.user, data['owner'], data['distro_series'], data['name'],
            **kwargs)
        self.next_url = canonical_url(snap)

    def validate(self, data):
        super(SnapAddView, self).validate(data)
        owner = data.get('owner', None)
        name = data.get('name', None)
        if owner and name:
            if getUtility(ISnapSet).exists(owner, name):
                self.setFieldError(
                    'name',
                    'There is already a snap package owned by %s with this '
                    'name.' % owner.displayname)


class BaseSnapEditView(LaunchpadEditFormView):

    schema = ISnapEditSchema

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    def setUpWidgets(self):
        """See `LaunchpadFormView`."""
        super(BaseSnapEditView, self).setUpWidgets()
        widget = self.widgets.get('vcs')
        if widget is not None:
            current_value = widget._getFormValue()
            self.vcs_bzr_radio, self.vcs_git_radio = [
                render_radio_widget_part(widget, value, current_value)
                for value in (VCSType.BZR, VCSType.GIT)]

    def validate_widgets(self, data, names=None):
        """See `LaunchpadFormView`."""
        if 'vcs' in self.widgets:
            # Set widgets as required or optional depending on the vcs
            # field.
            super(BaseSnapEditView, self).validate_widgets(data, ['vcs'])
            vcs = data.get('vcs')
            if vcs == VCSType.BZR:
                self.widgets['branch'].context.required = True
                self.widgets['git_ref'].context.required = False
            elif vcs == VCSType.GIT:
                self.widgets['branch'].context.required = False
                self.widgets['git_ref'].context.required = True
            else:
                raise AssertionError("Unknown branch type %s" % vcs)
        super(BaseSnapEditView, self).validate_widgets(data, names=names)

    @action('Update snap package', name='update')
    def request_action(self, action, data):
        vcs = data.pop('vcs', None)
        if vcs == VCSType.BZR:
            data['git_ref'] = None
        elif vcs == VCSType.GIT:
            data['branch'] = None
        self.updateContextFromData(data)
        self.next_url = canonical_url(self.context)

    @property
    def adapters(self):
        """See `LaunchpadFormView`."""
        return {ISnapEditSchema: self.context}


class SnapAdminView(BaseSnapEditView):
    """View for administering snap packages."""

    @property
    def label(self):
        return 'Administer %s snap package' % self.context.name

    page_title = 'Administer'

    field_names = ['require_virtualized']


class SnapEditView(BaseSnapEditView):
    """View for editing snap packages."""

    @property
    def label(self):
        return 'Edit %s snap package' % self.context.name

    page_title = 'Edit'

    field_names = [
        'owner', 'name', 'distro_series', 'vcs', 'branch', 'git_ref']
    custom_widget('distro_series', LaunchpadRadioWidget)
    custom_widget('vcs', LaunchpadRadioWidget)
    custom_widget('git_ref', GitRefWidget)

    @property
    def initial_values(self):
        if self.context.git_ref is not None:
            vcs = VCSType.GIT
        else:
            vcs = VCSType.BZR
        return {'vcs': vcs}

    def validate(self, data):
        super(SnapEditView, self).validate(data)
        owner = data.get('owner', None)
        name = data.get('name', None)
        if owner and name:
            try:
                snap = getUtility(ISnapSet).getByName(owner, name)
                if snap != self.context:
                    self.setFieldError(
                        'name',
                        'There is already a snap package owned by %s with '
                        'this name.' % owner.displayname)
            except NoSuchSnap:
                pass


class SnapDeleteView(BaseSnapEditView):
    """View for deleting snap packages."""

    @property
    def label(self):
        return 'Delete %s snap package' % self.context.name

    page_title = 'Delete'

    field_names = []

    @property
    def has_builds(self):
        return not self.context.builds.is_empty()

    @action('Delete snap package', name='delete')
    def delete_action(self, action, data):
        owner = self.context.owner
        self.context.destroySelf()
        # XXX cjwatson 2015-07-17: This should go to Person:+snaps or
        # similar (or something on SnapSet?) once that exists.
        self.next_url = canonical_url(owner)
