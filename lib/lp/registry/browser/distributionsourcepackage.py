# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'DistributionSourcePackageBreadcrumb',
    'DistributionSourcePackageEditView',
    'DistributionSourcePackageFacets',
    'DistributionSourcePackageNavigation',
    'DistributionSourcePackageOverviewMenu',
    'DistributionSourcePackageView',
    ]

from datetime import datetime
import itertools
import operator
import pytz

from zope.component import getUtility
from zope.formlib import form
from zope.interface import implements, Interface
from zope.schema import Choice
from zope.schema.vocabulary import SimpleTerm, SimpleVocabulary

from canonical.cachedproperty import cachedproperty
from canonical.launchpad import _
from lp.answers.interfaces.questionenums import QuestionStatus
from lp.soyuz.interfaces.archive import IArchiveSet
from lp.soyuz.interfaces.distributionsourcepackagerelease import (
    IDistributionSourcePackageRelease)
from lp.soyuz.interfaces.packagediff import IPackageDiffSet
from canonical.launchpad.interfaces.packaging import IPackagingUtil
from lp.soyuz.interfaces.publishing import pocketsuffix
from lp.registry.interfaces.product import IDistributionSourcePackage
from lp.bugs.browser.bugtask import BugTargetTraversalMixin
from lp.answers.browser.questiontarget import (
        QuestionTargetFacetMixin, QuestionTargetTraversalMixin)
from canonical.launchpad.browser.structuralsubscription import (
    StructuralSubscriptionTargetTraversalMixin)
from canonical.launchpad.webapp import (
    ApplicationMenu, LaunchpadEditFormView, LaunchpadFormView, Link,
    Navigation, StandardLaunchpadFacets, action, canonical_url, redirection)
from canonical.launchpad.webapp.menu import (
    enabled_with_permission, NavigationMenu)
from canonical.launchpad.webapp.breadcrumb import Breadcrumb

from lazr.delegates import delegates
from canonical.lazr.utils import smartquote


class DistributionSourcePackageBreadcrumb(Breadcrumb):
    """Builds a breadcrumb for an `IDistributionSourcePackage`."""
    @property
    def text(self):
        return smartquote('"%s" package') % (
            self.context.sourcepackagename.name)


class DistributionSourcePackageFacets(QuestionTargetFacetMixin,
                                      StandardLaunchpadFacets):

    usedfor = IDistributionSourcePackage
    enable_only = ['overview', 'bugs', 'answers', 'branches']


class DistributionSourcePackageLinksMixin:
    def subscribe(self):
        return Link('+subscribe', 'Subscribe to bug mail', icon='edit')

    def publishinghistory(self):
        return Link('+publishinghistory', 'Show publishing history')

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        """Edit the details of this source package."""
        # This is titled "Edit bug reporting guidelines" because that
        # is the only editable property of a source package right now.
        return Link('+edit', 'Edit bug reporting guidelines', icon='edit')

    def new_bugs(self):
        base_path = "+bugs"
        get_data = "?field.status:list=NEW"
        return Link(base_path + get_data, "New bugs", site="bugs")

    def open_questions(self):
        base_path = "+questions"
        get_data = "?field.status=OPEN"
        return Link(base_path + get_data, "Open Questions", site="answers")


class DistributionSourcePackageOverviewMenu(
    ApplicationMenu, DistributionSourcePackageLinksMixin):

    usedfor = IDistributionSourcePackage
    facet = 'overview'
    links = [
        'subscribe', 'publishinghistory', 'edit', 'new_bugs',
        'open_questions']


class DistributionSourcePackageBugsMenu(
        DistributionSourcePackageOverviewMenu):

    usedfor = IDistributionSourcePackage
    facet = 'bugs'
    links = ['filebug', 'subscribe']

    def filebug(self):
        text = 'Report a bug'
        return Link('+filebug', text, icon='bug')


class DistributionSourcePackageNavigation(Navigation,
    BugTargetTraversalMixin, QuestionTargetTraversalMixin,
    StructuralSubscriptionTargetTraversalMixin):

    usedfor = IDistributionSourcePackage

    redirection("+editbugcontact", "+subscribe")

    def traverse(self, name):
        return self.context.getVersion(name)


class DecoratedDistributionSourcePackageRelease:
    """A decorated DistributionSourcePackageRelease.

    The publishing history and package diffs for the release are
    pre-cached.
    """
    delegates(IDistributionSourcePackageRelease, 'context')

    def __init__(self, distributionsourcepackagerelease,
                 publishing_history, package_diffs):
        self.context = distributionsourcepackagerelease
        self._publishing_history = publishing_history
        self._package_diffs = package_diffs

    @property
    def publishing_history(self):
        """ See `IDistributionSourcePackageRelease`."""
        return self._publishing_history

    @property
    def package_diffs(self):
        """ See `ISourcePackageRelease`."""
        return self._package_diffs


class IDistributionSourcePackageActionMenu(Interface):
    """Marker interface for the action menu."""


class DistributionSourcePackageActionMenu(
    NavigationMenu, DistributionSourcePackageLinksMixin):
    """Action menu for distro source packages."""
    usedfor = IDistributionSourcePackageActionMenu
    facet = 'overview'
    title = 'Actions'
    links = ('change_log', 'subscribe', 'edit')

    def change_log(self):
        text = 'View full change log'
        return Link('+changelog', text, icon="info")


class DistributionSourcePackageView(LaunchpadFormView):
    implements(IDistributionSourcePackageActionMenu)

    @property
    def page_title(self):
        return self.context.title

    def setUpFields(self):
        """See `LaunchpadFormView`."""
        # No schema is set in this form, because all fields are created with
        # custom vocabularies. So we must not call the inherited setUpField
        # method.
        self.form_fields = self._createPackagingField()

    @property
    def can_delete_packaging(self):
        """Whether the user can delete existing packaging links."""
        return self.user is not None

    @property
    def all_published_in_active_distroseries(self):
        """Return a list of publishings in each active distroseries.

        The list contains dictionaries each with a key of "suite" and
        "description" where suite is "distroseries-pocket" and
        description is "(version): component/section".
        """
        results = []
        for pub in self.context.current_publishing_records:
            if pub.distroseries.active:
                entry = {
                    "suite" : (pub.distroseries.name.capitalize() +
                               pocketsuffix[pub.pocket]),
                    "description" : "(%s): %s/%s" % (
                        pub.sourcepackagerelease.version,
                        pub.component.name, pub.section.name)
                    }
                results.append(entry)
        return results

    @property
    def related_ppa_versions(self):
        """Return a list of the latest 3 ppas with related publishings.

        The list contains dictionaries each with a key of 'archive' and
        'publications'.
        """
        # Grab the related archive publications and limit the result to
        # the first 3.
        # XXX Michael Nelson 2009-06-24 bug=387020
        # Currently we need to find distinct archives here manually because,
        # without a concept of IArchive.rank or similar, the best ordering
        # that orderDistributionSourcePackage.findRelatedArchives() method
        # can provide is on a join (SourcePackageRelease.dateuploaded), but
        # this prohibits a distinct clause.
        # To ensure that we find distinct archives here with only one query,
        # we grab the first 20 results and iterate through to find three
        # distinct archives (20 is a magic number being greater than
        # 3 * number of distroseries).
        related_archives = self.context.findRelatedArchives()
        related_archives.config(limit=20)
        top_three_archives = []
        for archive in related_archives:
            if archive in top_three_archives:
                continue
            else:
                top_three_archives.append(archive)

            if len(top_three_archives) == 3:
                break

        # Now we'll find the relevant publications for the top
        # three archives.
        archive_set = getUtility(IArchiveSet)
        publications = archive_set.getPublicationsInArchives(
                self.context.sourcepackagename, top_three_archives,
                self.context.distribution)

        # Collect the publishings for each archive
        archive_publishings = {}
        for pub in publications:
            archive_publishings.setdefault(pub.archive, []).append(pub)

        # Then construct a list of dicts with the results for easy use in
        # the template, preserving the order of the archives:
        archive_versions = []
        for archive in top_three_archives:
            versions = []

            # For each publication, append something like:
            # 'Jaunty (1.0.1b)' to the versions list.
            for pub in archive_publishings[archive]:
                versions.append(
                    "%s (%s)" % (
                        pub.distroseries.displayname,
                        pub.source_package_version
                        )
                    )
            archive_versions.append({
                'archive': archive,
                'versions': ", ".join(versions)
                })

        return archive_versions

    @property
    def further_ppa_versions_url(self):
        """Return the url used to find further PPA versions of this package.
        """
        return "%s/+ppas?name_filter=%s" % (
            canonical_url(self.context.distribution),
            self.context.name,
            )

    def _createPackagingField(self):
        """Create a field to specify a Packaging association.

        Create a contextual vocabulary that can specify one of the Packaging
        associated to this DistributionSourcePackage.
        """
        terms = []
        for sourcepackage in self.context.get_distroseries_packages():
            packaging = sourcepackage.direct_packaging
            if packaging is None:
                continue
            terms.append(SimpleTerm(packaging, packaging.id))
        return form.Fields(
            Choice(__name__='packaging', vocabulary=SimpleVocabulary(terms),
                   required=True))

    def _renderHiddenPackagingField(self, packaging):
        """Render a hidden input that fills in the packaging field."""
        if not self.can_delete_packaging:
            return None
        vocabulary = self.form_fields['packaging'].field.vocabulary
        return '<input type="hidden" name="field.packaging" value="%s" />' % (
            vocabulary.getTerm(packaging).token)

    def renderDeletePackagingAction(self):
        """Render a submit input for the delete_packaging_action."""
        assert self.can_delete_packaging, 'User cannot delete Packaging.'
        return ('<input type="submit" class="button" value="Delete Link" '
                'style="padding: 0pt; font-size: 80%%" '
                'name="%s"/>' % (self.delete_packaging_action.__name__,))

    def handleDeletePackagingError(self, action, data, errors):
        """Handle errors on package link deletion.

        If 'packaging' is not set in the form data, we assume that means the
        provided Packaging id was not found, which should only happen if the
        same Packaging object was concurrently deleted. In this case, we want
        to display a more informative error message than the default 'Invalid
        value'.
        """
        if data.get('packaging') is None:
            self.setFieldError(
                'packaging',
                _("This upstream association was deleted already."))

    @action(_("Delete Link"), name='delete_packaging',
            failure=handleDeletePackagingError)
    def delete_packaging_action(self, action, data):
        """Delete a Packaging association."""
        packaging = data['packaging']
        productseries = packaging.productseries
        distroseries = packaging.distroseries
        getUtility(IPackagingUtil).deletePackaging(
            productseries, packaging.sourcepackagename, distroseries)
        self.request.response.addNotification(
            _("Removed upstream association between ${product} "
              "${productseries} and ${distroseries}.", mapping=dict(
              product=productseries.product.displayname,
              productseries=productseries.displayname,
              distroseries=distroseries.displayname)))
        self.next_url = canonical_url(self.context)

    @cachedproperty
    def active_distroseries_packages(self):
        """Cached proxy call to context/get_distroseries_packages."""
        return self.context.get_distroseries_packages()

    @property
    def packages_by_active_distroseries(self):
        """Dict of packages keyed by distroseries."""
        packages_dict = {}
        for package in self.active_distroseries_packages:
            packages_dict[package.distroseries] = package
        return packages_dict

    @property
    def active_series(self):
        """Return active distroseries where this package is published.

        Used in the template code that shows the table of versions.
        The returned series are sorted in reverse order of creation.
        """
        series = set()
        for package in self.active_distroseries_packages:
            series.add(package.distroseries)
        result = list(series)
        result.sort(key=operator.attrgetter("version"), reverse=True)
        return result

    def published_by_version(self, sourcepackage):
        """Return a dict of publications keyed by version.

        :param sourcepackage: ISourcePackage
        """
        publications = sourcepackage.distroseries.getPublishedReleases(
            sourcepackage.sourcepackagename)
        pocket_dict = {}
        for pub in publications:
            version = pub.source_package_version
            if version not in pocket_dict:
                pocket_dict[version] = [pub]
            else:
                pocket_dict[version].append(pub)
        return pocket_dict

    @property
    def version_table(self):
        """Rows of data for the template to render in the packaging table."""
        rows = []
        packages_by_series = self.packages_by_active_distroseries
        for distroseries in self.active_series:
            # The first row for each series is the "title" row.
            packaging = packages_by_series[distroseries].direct_packaging
            if packaging is None:
                delete_packaging_form_id = None
                hidden_packaging_field = None
            else:
                delete_packaging_form_id = "delete_%s_%s_%s" % (
                    packaging.distroseries.name,
                    packaging.productseries.product.name,
                    packaging.productseries.name)
                hidden_packaging_field = self._renderHiddenPackagingField(
                    packaging)
            package = packages_by_series[distroseries]
            title_row = {
                'blank_row': False,
                'title_row': True,
                'data_row': False,
                'distroseries': distroseries,
                'series_package': package,
                'packaging': packaging,
                'hidden_packaging_field': hidden_packaging_field,
                'delete_packaging_form_id': delete_packaging_form_id,
                }
            rows.append(title_row)

            # After the title row, we list each package version that's
            # currently published, and which pockets it's published in.
            pocket_dict = self.published_by_version(package)
            for version in pocket_dict.iterkeys():
                most_recent_publication = pocket_dict[version][0]
                if most_recent_publication.datepublished is None:
                    published_since = None
                else:
                    published_since = datetime.now(
                        tz=pytz.UTC) - most_recent_publication.datepublished
                row = {
                    'blank_row': False,
                    'title_row': False,
                    'data_row': True,
                    'version': version,
                    'publication': most_recent_publication,
                    'pockets': ", ".join(
                        [pub.pocket.name for pub in pocket_dict[version]]),
                    'component': most_recent_publication.component_name,
                    'published_since': published_since,
                    }
                rows.append(row)
            # We need a blank row after each section, so the series
            # header row doesn't appear too close to the previous
            # section.
            rows.append({
                'blank_row': True,
                'title_row': False,
                'data_row': False,
                })

        return rows

    def releases(self):
        dspr_pubs = self.context.getReleasesAndPublishingHistory()

        # Return as early as possible to avoid unnecessary processing.
        if len(dspr_pubs) == 0:
            return []

        # Collate diffs for relevant SourcePackageReleases
        sprs = [dspr.sourcepackagerelease for (dspr, spphs) in dspr_pubs]
        pkg_diffs = getUtility(IPackageDiffSet).getDiffsToReleases(sprs)
        spr_diffs = {}
        for spr, diffs in itertools.groupby(pkg_diffs,
                                            operator.attrgetter('to_source')):
            spr_diffs[spr] = list(diffs)

        return [
            DecoratedDistributionSourcePackageRelease(
                dspr, spphs, spr_diffs.get(dspr.sourcepackagerelease, []))
            for (dspr, spphs) in dspr_pubs]

    @cachedproperty
    def open_questions(self):
        """Return result set containing open questions for this package."""
        return self.context.searchQuestions(status=QuestionStatus.OPEN)


class DistributionSourcePackageEditView(LaunchpadEditFormView):
    """Edit a distribution source package."""

    schema = IDistributionSourcePackage
    field_names = [
        'bug_reporting_guidelines',
        ]

    @property
    def label(self):
        """The form label."""
        return 'Edit %s' % self.context.title

    @property
    def page_title(self):
        """The page title."""
        return self.label

    @action("Change", name='change')
    def change_action(self, action, data):
        self.updateContextFromData(data)

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url
