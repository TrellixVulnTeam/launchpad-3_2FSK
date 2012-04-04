# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Common views for objects that implement `IPillar`."""

__metaclass__ = type

__all__ = [
    'InvolvedMenu', 'PillarBugsMenu', 'PillarView',
    'PillarNavigationMixin',
    'PillarPersonSharingView',
    'PillarSharingView',
    ]


from operator import attrgetter

from lazr.restful import ResourceJSONEncoder
from lazr.restful.interfaces import IJSONRequestCache
from lazr.restful.utils import get_current_web_service_request
import simplejson
from zope.component import getUtility
from zope.interface import (
    implements,
    Interface,
    )
from zope.schema.interfaces import IVocabulary
from zope.schema.vocabulary import getVocabularyRegistry
from zope.security.interfaces import Unauthorized
from zope.traversing.browser.absoluteurl import absoluteURL

from lp.app.browser.launchpad import iter_view_registrations
from lp.app.browser.tales import MenuAPI
from lp.app.browser.vocabulary import vocabulary_filters
from lp.app.enums import (
    service_uses_launchpad,
    ServiceUsage,
    )
from lp.app.interfaces.launchpad import IServiceUsage
from lp.app.interfaces.services import IService
from lp.bugs.browser.structuralsubscription import (
    StructuralSubscriptionMenuMixin,
    )
from lp.bugs.interfaces.bug import IBug
from lp.code.interfaces.branch import IBranch
from lp.registry.interfaces.accesspolicy import (
    IAccessPolicyGrantFlatSource,
    IAccessPolicySource,
    )
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
    )
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.pillar import IPillar
from lp.registry.interfaces.projectgroup import IProjectGroup
from lp.registry.model.pillar import PillarPerson
from lp.services.config import config
from lp.services.features import getFeatureFlag
from lp.services.propertycache import cachedproperty
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.batching import (
    BatchNavigator,
    StormRangeFactory,
    )
from lp.services.webapp.menu import (
    ApplicationMenu,
    enabled_with_permission,
    Link,
    NavigationMenu,
    )
from lp.services.webapp.publisher import (
    canonical_url,
    LaunchpadView,
    nearest,
    stepthrough,
    )


class PillarNavigationMixin:

    @stepthrough('+sharingdetails')
    def traverse_details(self, name):
        """Traverse to the sharing details for a given person."""
        person = getUtility(IPersonSet).getByName(name)
        if person is None:
            return None
        policies = getUtility(IAccessPolicySource).findByPillar([self.context])
        source = getUtility(IAccessPolicyGrantFlatSource)
        artifacts = source.findArtifactsByGrantee(person, policies)
        if artifacts.is_empty():
            return None
        return PillarPerson.create(self.context, person)


class IInvolved(Interface):
    """A marker interface for getting involved."""


class InvolvedMenu(NavigationMenu):
    """The get involved menu."""
    usedfor = IInvolved
    links = [
        'report_bug', 'ask_question', 'help_translate', 'register_blueprint']

    @property
    def pillar(self):
        return self.context

    def report_bug(self):
        return Link(
            '+filebug', 'Report a bug', site='bugs', icon='bugs',
            enabled=self.pillar.official_malone)

    def ask_question(self):
        return Link(
            '+addquestion', 'Ask a question', site='answers', icon='answers',
            enabled=service_uses_launchpad(self.pillar.answers_usage))

    def help_translate(self):
        return Link(
            '', 'Help translate', site='translations', icon='translations',
            enabled=service_uses_launchpad(self.pillar.translations_usage))

    def register_blueprint(self):
        return Link(
            '+addspec',
            'Register a blueprint',
            site='blueprints',
            icon='blueprints',
            enabled=service_uses_launchpad(self.pillar.blueprints_usage))


class PillarView(LaunchpadView):
    """A view for any `IPillar`."""
    implements(IInvolved)

    configuration_links = []
    visible_disabled_link_names = []

    def __init__(self, context, request):
        super(PillarView, self).__init__(context, request)
        self.official_malone = False
        self.answers_usage = ServiceUsage.UNKNOWN
        self.blueprints_usage = ServiceUsage.UNKNOWN
        self.translations_usage = ServiceUsage.UNKNOWN
        self.codehosting_usage = ServiceUsage.UNKNOWN
        pillar = nearest(self.context, IPillar)

        self._set_official_launchpad(pillar)
        if IDistroSeries.providedBy(self.context):
            distribution = self.context.distribution
            self.codehosting_usage = distribution.codehosting_usage
            self.answers_usage = ServiceUsage.NOT_APPLICABLE
        elif IDistributionSourcePackage.providedBy(self.context):
            self.blueprints_usage = ServiceUsage.UNKNOWN
            self.translations_usage = ServiceUsage.UNKNOWN
        elif IProjectGroup.providedBy(pillar):
            # XXX: 2010-10-07 EdwinGrubbs bug=656292
            # Fix _set_official_launchpad().

            # Project groups do not support submit code, override the
            # default.
            self.codehosting_usage = ServiceUsage.NOT_APPLICABLE
        else:
            # The context is used by all apps.
            pass

    def _set_official_launchpad(self, pillar):
        """Does the pillar officially use launchpad."""
        # XXX: 2010-10-07 EdwinGrubbs bug=656292
        # Fix _set_official_launchpad().
        # This if structure is required because it may be called many
        # times to build the complete set of official applications.
        if service_uses_launchpad(IServiceUsage(pillar).bug_tracking_usage):
            self.official_malone = True
        if service_uses_launchpad(IServiceUsage(pillar).answers_usage):
            self.answers_usage = ServiceUsage.LAUNCHPAD
        if service_uses_launchpad(IServiceUsage(pillar).blueprints_usage):
            self.blueprints_usage = ServiceUsage.LAUNCHPAD
        if service_uses_launchpad(pillar.translations_usage):
            self.translations_usage = ServiceUsage.LAUNCHPAD
        if service_uses_launchpad(IServiceUsage(pillar).codehosting_usage):
            self.codehosting_usage = ServiceUsage.LAUNCHPAD

    @property
    def has_involvement(self):
        """This `IPillar` uses Launchpad."""
        return (self.official_malone
            or service_uses_launchpad(self.answers_usage)
            or service_uses_launchpad(self.blueprints_usage)
            or service_uses_launchpad(self.translations_usage)
            or service_uses_launchpad(self.codehosting_usage))

    @property
    def enabled_links(self):
        """The enabled involvement links."""
        menuapi = MenuAPI(self)
        return sorted([
            link for link in menuapi.navigation.values() if link.enabled],
            key=attrgetter('sort_key'))

    @cachedproperty
    def visible_disabled_links(self):
        """Important disabled links.

        These are displayed to notify the user to provide configuration
        info to enable the links.

        Override the visible_disabled_link_names attribute to change
        the results.
        """
        involved_menu = MenuAPI(self).navigation
        important_links = [
            involved_menu[name]
            for name in self.visible_disabled_link_names]
        return sorted([
            link for link in important_links if not link.enabled],
            key=attrgetter('sort_key'))

    @property
    def registration_completeness(self):
        """The percent complete for registration.

        Not used by all pillars.
        """
        return None


class PillarBugsMenu(ApplicationMenu, StructuralSubscriptionMenuMixin):
    """Base class for pillar bugs menus."""

    facet = 'bugs'
    configurable_bugtracker = False

    @enabled_with_permission('launchpad.Edit')
    def bugsupervisor(self):
        text = 'Change bug supervisor'
        return Link('+bugsupervisor', text, icon='edit')

    def cve(self):
        text = 'CVE reports'
        return Link('+cve', text, icon='cve')

    def filebug(self):
        text = 'Report a bug'
        return Link('+filebug', text, icon='bug')

    @enabled_with_permission('launchpad.Edit')
    def securitycontact(self):
        text = 'Change security contact'
        return Link('+securitycontact', text, icon='edit')


class PillarSharingView(LaunchpadView):

    page_title = "Sharing"
    label = "Sharing information"

    related_features = (
        'disclosure.enhanced_sharing.enabled',
        'disclosure.enhanced_sharing.writable',
        )

    _batch_navigator = None

    def _getSharingService(self):
        return getUtility(IService, 'sharing')

    @property
    def information_types(self):
        return self._getSharingService().getInformationTypes(self.context)

    @property
    def sharing_permissions(self):
        return self._getSharingService().getSharingPermissions()

    @cachedproperty
    def sharing_vocabulary(self):
        registry = getVocabularyRegistry()
        return registry.get(
            IVocabulary, 'ValidPillarOwner')

    @cachedproperty
    def sharing_vocabulary_filters(self):
        return vocabulary_filters(self.sharing_vocabulary)

    @property
    def sharing_picker_config(self):
        return dict(
            vocabulary='NewPillarSharee',
            vocabulary_filters=self.sharing_vocabulary_filters,
            header='Share with a user or team')

    @property
    def json_sharing_picker_config(self):
        return simplejson.dumps(
            self.sharing_picker_config, cls=ResourceJSONEncoder)

    def _getBatchNavigator(self, sharees):
        """Return the batch navigator to be used to batch the sharees."""
        return BatchNavigator(
            sharees, self.request,
            hide_counts=True,
            size=config.launchpad.default_batch_size,
            range_factory=StormRangeFactory(sharees))

    def sharees(self):
        """An `IBatchNavigator` for sharees."""
        if self._batch_navigator is None:
            unbatchedSharees = self.unbatched_sharees()
            self._batch_navigator = self._getBatchNavigator(unbatchedSharees)
        return self._batch_navigator

    def unbatched_sharees(self):
        """All the sharees for a pillar."""
        return self._getSharingService().getPillarSharees(self.context)

    def initialize(self):
        super(PillarSharingView, self).initialize()
        enabled_readonly_flag = 'disclosure.enhanced_sharing.enabled'
        enabled_writable_flag = (
            'disclosure.enhanced_sharing.writable')
        enabled = bool(getFeatureFlag(enabled_readonly_flag))
        write_flag_enabled = bool(getFeatureFlag(enabled_writable_flag))
        if not enabled and not write_flag_enabled:
            raise Unauthorized("This feature is not yet available.")
        cache = IJSONRequestCache(self.request)
        cache.objects['sharing_write_enabled'] = (write_flag_enabled
            and check_permission('launchpad.Edit', self.context))
        cache.objects['information_types'] = self.information_types
        cache.objects['sharing_permissions'] = self.sharing_permissions

        view_names = set(reg.name for reg
            in iter_view_registrations(self.__class__))
        if len(view_names) != 1:
            raise AssertionError("Ambiguous view name.")
        cache.objects['view_name'] = view_names.pop()
        batch_navigator = self.sharees()
        cache.objects['sharee_data'] = (
            self._getSharingService().jsonShareeData(batch_navigator.batch))

        def _getBatchInfo(batch):
            if batch is None:
                return None
            return {'memo': batch.range_memo,
                    'start': batch.startNumber() - 1}

        next_batch = batch_navigator.batch.nextBatch()
        cache.objects['next'] = _getBatchInfo(next_batch)
        prev_batch = batch_navigator.batch.prevBatch()
        cache.objects['prev'] = _getBatchInfo(prev_batch)
        cache.objects['total'] = batch_navigator.batch.total()
        cache.objects['forwards'] = batch_navigator.batch.range_forwards
        last_batch = batch_navigator.batch.lastBatch()
        cache.objects['last_start'] = last_batch.startNumber() - 1
        cache.objects.update(_getBatchInfo(batch_navigator.batch))


class PillarPersonSharingView(LaunchpadView):

    page_title = "Person or team"
    label = "Information shared with person or team"

    def initialize(self):
        enabled_flag = 'disclosure.enhanced_sharing_details.enabled'
        enabled = bool(getFeatureFlag(enabled_flag))
        if not enabled:
            raise Unauthorized("This feature is not yet available.")

        self.pillar = self.context.pillar
        self.person = self.context.person

        self.label = "Information shared with %s" % self.person.displayname
        self.page_title = "%s" % self.person.displayname
        self.sharing_service = getUtility(IService, 'sharing')

        self._loadSharedArtifacts()

        cache = IJSONRequestCache(self.request)
        request = get_current_web_service_request()
        branch_data = self._build_branch_template_data(self.branches, request)
        bug_data = self._build_bug_template_data(self.bugs, request)
        sharee_data = {
            'displayname': self.person.displayname,
            'self_link': absoluteURL(self.person, request)
        }
        pillar_data = {
            'self_link': absoluteURL(self.pillar, request)
        }
        cache.objects['sharee'] = sharee_data
        cache.objects['pillar'] = pillar_data
        cache.objects['bugs'] = bug_data
        cache.objects['branches'] = branch_data
        enabled_writable_flag = (
            'disclosure.enhanced_sharing.writable')
        write_flag_enabled = bool(getFeatureFlag(enabled_writable_flag))
        cache.objects['sharing_write_enabled'] = (write_flag_enabled
            and check_permission('launchpad.Edit', self.pillar))

    def _loadSharedArtifacts(self):
        bugs = []
        branches = []
        for artifact in self.sharing_service.getSharedArtifacts(
                            self.pillar, self.person):
            concrete = artifact.concrete_artifact
            if IBug.providedBy(concrete):
                bugs.append(concrete)
            elif IBranch.providedBy(concrete):
                branches.append(concrete)

        self.bugs = bugs
        self.branches = branches
        self.shared_bugs_count = len(bugs)
        self.shared_branches_count = len(branches)

    def _build_branch_template_data(self, branches, request):
        branch_data = []
        for branch in branches:
            branch_data.append(dict(
                self_link=absoluteURL(branch, request),
                web_link=canonical_url(branch, path_only_if_possible=True),
                branch_name=branch.unique_name,
                branch_id=branch.id))
        return branch_data

    def _build_bug_template_data(self, bugs, request):
        bug_data = []
        for bug in bugs:
            web_link = canonical_url(bug, path_only_if_possible=True)
            self_link = absoluteURL(bug, request)
            importance = bug.default_bugtask.importance.title.lower()
            bug_data.append(dict(
                self_link=self_link,
                web_link=web_link,
                bug_summary=bug.title,
                bug_id=bug.id,
                bug_importance=importance))
        return bug_data
