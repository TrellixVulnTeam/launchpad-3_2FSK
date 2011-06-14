# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Initialise a distroseries from its parent distroseries."""


__metaclass__ = type
__all__ = [
    'InitialisationError',
    'InitialiseDistroSeries',
    ]

from operator import methodcaller

import transaction
from zope.component import getUtility

from canonical.database.sqlbase import sqlvalues
from canonical.launchpad.helpers import ensure_unicode
from canonical.launchpad.interfaces.lpstorm import IMasterStore
from lp.app.errors import NotFoundError
from lp.buildmaster.enums import BuildStatus
from lp.registry.interfaces.distroseriesparent import IDistroSeriesParentSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.database import bulk
from lp.soyuz.adapters.packagelocation import PackageLocation
from lp.soyuz.enums import (
    ArchivePurpose,
    PackageUploadStatus,
    )
from lp.soyuz.interfaces.archive import IArchiveSet
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.packagecloner import IPackageCloner
from lp.soyuz.interfaces.packageset import (
    IPackagesetSet,
    NoSuchPackageSet,
    )
from lp.soyuz.model.packageset import Packageset


class InitialisationError(Exception):
    """Raised when there is an exception during the initialisation process."""


class InitialiseDistroSeries:
    """Copy in all of the parents distroseries's configuration. This
    includes all configuration for distroseries as well as distroarchseries,
    publishing and all publishing records for sources and binaries.

    We support 2 use cases here:
      #1 If the child distribution has zero initialized series:
        - the parent list can't be empty (otherwise we trigger an error);
        - the series will be derived from the parents passed as argument;
        - the parents will be set to the parents passed as argument;
        - first_derivation = True.
      #2 If the child distribution has more than zero initialized series:
        - the series will be derived from the previous_series;
        - the parents will be set to the parents passed as argument or
          the parents of the previous_series if the passed argument is empty;
        - first_derivation = False.

    Preconditions:
      The distroseries must exist, and be completly unused, with no source
      or binary packages existing, as well as no distroarchseries set up.
      Section and component selections must be empty. It must not have any
      parent series.

    Outcome:
      The distroarchseries set up in the parent series will be copied.
      The publishing structure will be copied from the parents. All
      PUBLISHED and PENDING packages in the parents will be created in
      this distroseries and its distroarchseriess. All component and section
      selections will be duplicated, as will any permission-related
      structures.

    Note:
      This method will raise a InitialisationError when the pre-conditions
      are not met. After this is run, you still need to construct chroots
      for building, you need to add anything missing wrt. ports etc. This
      method is only meant to give you a basic copy of parent series in
      order to assist you in preparing a new series of a distribution or
      in the initialisation of a derivative.
    """

    def __init__(
        self, distroseries, parents=(), arches=(), packagesets=(),
        rebuild=False, overlays=(), overlay_pockets=(),
        overlay_components=()):
        # Avoid circular imports
        from lp.registry.model.distroseries import DistroSeries

        self.distroseries = distroseries
        self.parent_ids = [int(id) for id in parents]
        # Load parent objects in bulk...
        parents_bulk = bulk.load(DistroSeries, self.parent_ids)
        # ... sort the parents to match the order in the 'parents' parameter.
        self.parents = sorted(
            parents_bulk,
            key=lambda parent: self.parent_ids.index(parent.id))
        self.arches = arches
        self.packagesets = [
            ensure_unicode(packageset) for packageset in packagesets]
        self.rebuild = rebuild
        self.overlays = overlays
        self.overlay_pockets = overlay_pockets
        self.overlay_components = overlay_components
        self._store = IMasterStore(DistroSeries)

        self.first_derivation = (
            not self.distroseries.distribution.has_published_sources)
        if self.first_derivation:
            # Use-case #1.
            self.derivation_parents = self.parents
            self.derivation_parent_ids = self.parent_ids
        else:
            # Use-case #2.
            self.derivation_parents = [self.distroseries.previous_series]
            self.derivation_parent_ids = [
                p.id for p in self.derivation_parents]
            if self.parent_ids == []:
                self.parents = (
                    self.distroseries.previous_series.getParentSeries())

    def check(self):
        if self.distroseries.is_derived_series:
            raise InitialisationError(
                ("DistroSeries {child.name} has already been initialized"
                 ".").format(
                    child=self.distroseries))
        self._checkParents()
        for parent in self.derivation_parents:
            if self.distroseries.distribution.id == parent.distribution.id:
                self._checkBuilds(parent)
            self._checkQueue(parent)
        self._checkSeries()

    def _checkParents(self):
        """If self.first_derivation, the parents list cannot be empty."""
        if self.first_derivation:
            # Use-case #1.
            if len(self.parent_ids) == 0:
                raise InitialisationError(
                    ("Distroseries {child.name} cannot be initialized: "
                     "No other series in the distribution is initialized "
                     "and no parent was passed to the initilization method"
                     ".").format(
                        child=self.distroseries))

    def _checkBuilds(self, parent):
        """Assert there are no pending builds for the given parent series.

        Only cares about the RELEASE pocket, which is the only one inherited
        via initialiseFromParent method.
        """
        # only the RELEASE pocket is inherited, so we only check
        # pending build records for it.
        pending_builds = parent.getBuildRecords(
            BuildStatus.NEEDSBUILD, pocket=PackagePublishingPocket.RELEASE)

        if pending_builds.any():
            raise InitialisationError("Parent series has pending builds.")

    def _checkQueue(self, parent):
        """Assert upload queue is empty on the given parent series.

        Only cares about the RELEASE pocket, which is the only one inherited
        via initialiseFromParent method.
        """
        # only the RELEASE pocket is inherited, so we only check
        # queue items for it.
        for queue in (
            PackageUploadStatus.NEW, PackageUploadStatus.ACCEPTED,
            PackageUploadStatus.UNAPPROVED):
            items = parent.getQueueItems(
                queue, pocket=PackagePublishingPocket.RELEASE)
            if items:
                raise InitialisationError(
                    "Parent series queues are not empty.")

    def _checkSeries(self):
        error = (
            "Can not copy distroarchseries from parent, there are "
            "already distroarchseries(s) initialised for this series.")
        sources = self.distroseries.getAllPublishedSources()
        binaries = self.distroseries.getAllPublishedBinaries()
        if not all(
            map(methodcaller('is_empty'), (
                sources, binaries, self.distroseries.architectures,
                self.distroseries.sections))):
            raise InitialisationError(error)
        if self.distroseries.components:
            raise InitialisationError(error)

    def initialise(self):
        self._set_parents()
        self._copy_configuration()
        self._copy_architectures()
        self._copy_packages()
        self._copy_packagesets()
        self._set_initialised()
        transaction.commit()

    def _set_parents(self):
        count = 0
        for parent in self.parents:
            dsp_set = getUtility(IDistroSeriesParentSet)
            if self.overlays and self.overlays[count]:
                pocket = PackagePublishingPocket.__metaclass__.getTermByToken(
                    PackagePublishingPocket,
                    self.overlay_pockets[count]).value
                component_set = getUtility(IComponentSet)
                component = component_set[self.overlay_components[count]]
                dsp_set.new(
                    self.distroseries, parent, initialized=False,
                    is_overlay=True, pocket=pocket, component=component,
                    ordering=count + 1)
            else:
                dsp_set.new(
                    self.distroseries, parent, initialized=False,
                    is_overlay=False, ordering=count + 1)
            count += 1

    def _set_initialised(self):
        dsp_set = getUtility(IDistroSeriesParentSet)
        distroseriesparents = dsp_set.getByDerivedSeries(
            self.distroseries)
        for distroseriesparent in distroseriesparents:
            distroseriesparent.initialized = True

    def _copy_configuration(self):
        self.distroseries.backports_not_automatic = any(
            parent.backports_not_automatic
                for parent in self.derivation_parents)

    def _copy_architectures(self):
        das_filter = ' AND distroseries IN %s ' % (
                sqlvalues([p.id for p in self.derivation_parents]))
        if self.arches:
            das_filter += ' AND architecturetag IN %s ' % (
                sqlvalues(self.arches))
        self._store.execute("""
            INSERT INTO DistroArchSeries
            (distroseries, processorfamily, architecturetag, owner, official)
            SELECT %s, processorfamily, architecturetag, %s,
                bool_and(official)
            FROM DistroArchSeries WHERE enabled = TRUE %s
            GROUP BY processorfamily, architecturetag
            """ % (sqlvalues(self.distroseries, self.distroseries.owner)
            + (das_filter, )))
        self._store.flush()
        # Take nominatedarchindep from the first parent.
        self.distroseries.nominatedarchindep = self.distroseries[
            self.derivation_parents[0].nominatedarchindep.architecturetag]

    def _copy_packages(self):
        # Perform the copies
        self._copy_component_section_and_format_selections()

        # Prepare the lists of distroarchseries for which binary packages
        # shall be copied.
        distroarchseries_lists = {}
        for parent in self.derivation_parents:
            distroarchseries_lists[parent] = []
            for arch in self.distroseries.architectures:
                if self.arches and (arch.architecturetag not in self.arches):
                    continue
                try:
                    parent_arch = parent.getDistroArchSeries(
                        arch.architecturetag)
                except NotFoundError:
                    continue

                distroarchseries_lists[parent].append((parent_arch, arch))
        # Now copy source and binary packages.
        self._copy_publishing_records(distroarchseries_lists)
        self._copy_packaging_links()

    def _copy_publishing_records(self, distroarchseries_lists):
        """Copy the publishing records from the parent arch series
        to the given arch series in ourselves.

        We copy all PENDING and PUBLISHED records as PENDING into our own
        publishing records.

        We copy only the RELEASE pocket in the PRIMARY and DEBUG archives.
        """
        archive_set = getUtility(IArchiveSet)

        spns = []
        # The overhead from looking up each packageset is mitigated by
        # this usually running from a job.
        if self.packagesets:
            for pkgsetid in self.packagesets:
                pkgset = self._store.get(Packageset, int(pkgsetid))
                spns += list(pkgset.getSourcesIncluded())

        for parent in self.derivation_parents:
            distroarchseries_list = distroarchseries_lists[parent]
            for archive in parent.distribution.all_distro_archives:
                if archive.purpose not in (
                    ArchivePurpose.PRIMARY, ArchivePurpose.DEBUG):
                    continue

                target_archive = archive_set.getByDistroPurpose(
                    self.distroseries.distribution, archive.purpose)
                if archive.purpose is ArchivePurpose.PRIMARY:
                    assert target_archive is not None, (
                        "Target archive doesn't exist?")
                origin = PackageLocation(
                    archive, parent.distribution, parent,
                    PackagePublishingPocket.RELEASE)
                destination = PackageLocation(
                    target_archive, self.distroseries.distribution,
                    self.distroseries, PackagePublishingPocket.RELEASE)
                proc_families = None
                if self.rebuild:
                    proc_families = [
                        das[1].processorfamily
                        for das in distroarchseries_list]
                    distroarchseries_list = ()
                getUtility(IPackageCloner).clonePackages(
                    origin, destination, distroarchseries_list,
                    proc_families, spns, self.rebuild, no_duplicates=True)

    def _copy_component_section_and_format_selections(self):
        """Copy the section, component and format selections from the parents
        distro series into this one.
        """
        # Copy the component selections
        self._store.execute('''
            INSERT INTO ComponentSelection (distroseries, component)
            SELECT DISTINCT %s AS distroseries, cs.component AS component
            FROM ComponentSelection AS cs WHERE cs.distroseries IN %s
            ''' % sqlvalues(self.distroseries.id,
            self.derivation_parent_ids))
        # Copy the section selections
        self._store.execute('''
            INSERT INTO SectionSelection (distroseries, section)
            SELECT DISTINCT %s as distroseries, ss.section AS section
            FROM SectionSelection AS ss WHERE ss.distroseries IN %s
            ''' % sqlvalues(self.distroseries.id,
            self.derivation_parent_ids))
        # Copy the source format selections
        self._store.execute('''
            INSERT INTO SourcePackageFormatSelection (distroseries, format)
            SELECT DISTINCT %s as distroseries, spfs.format AS format
            FROM SourcePackageFormatSelection AS spfs
            WHERE spfs.distroseries IN %s
            ''' % sqlvalues(self.distroseries.id,
            self.derivation_parent_ids))

    def _copy_packaging_links(self):
        """Copy the packaging links from the parent series to this one."""
        # We iterate over the parents and copy into the child in
        # sequence to avoid creating duplicates.
        for parent_id in self.derivation_parent_ids:
            self._store.execute("""
                INSERT INTO
                    Packaging(
                        distroseries, sourcepackagename, productseries,
                        packaging, owner)
                SELECT
                    ChildSeries.id,
                    Packaging.sourcepackagename,
                    Packaging.productseries,
                    Packaging.packaging,
                    Packaging.owner
                FROM
                    Packaging
                    -- Joining the parent distroseries permits the query to
                    -- build the data set for the series being updated, yet
                    -- results are in fact the data from the original series.
                    JOIN Distroseries ChildSeries
                        ON Packaging.distroseries = %s
                WHERE
                    -- Select only the packaging links that are in the parent
                    -- that are not in the child.
                    ChildSeries.id = %s
                    AND Packaging.sourcepackagename in (
                        SELECT sourcepackagename
                        FROM Packaging
                        WHERE distroseries in (
                            SELECT id
                            FROM Distroseries
                            WHERE id = %s
                            )
                        EXCEPT
                        SELECT sourcepackagename
                        FROM Packaging
                        WHERE distroseries in (
                            SELECT id
                            FROM Distroseries
                            WHERE id = ChildSeries.id
                            )
                        )
                """ % sqlvalues(
                    parent_id, self.distroseries.id, parent_id))

    def _copy_packagesets(self):
        """Copy packagesets from the parent distroseries."""
        # Avoid circular imports.
        from lp.registry.model.distroseries import DistroSeries

        packagesets = self._store.find(
            Packageset, DistroSeries.id.is_in(self.derivation_parent_ids))
        parent_to_child = {}
        # Create the packagesets, and any archivepermissions
        parent_distro_ids = [
            parent.distribution.id for parent in self.derivation_parents]
        for parent_ps in packagesets:
            # Cross-distro initialisations get packagesets owned by the
            # distro owner, otherwise the old owner is preserved.
            if self.packagesets and str(parent_ps.id) not in self.packagesets:
                continue
            packageset_set = getUtility(IPackagesetSet)
            # First, try to fetch an existing packageset with this name.
            try:
                child_ps = packageset_set.getByName(
                    parent_ps.name, self.distroseries)
            except NoSuchPackageSet:
                if self.distroseries.distribution.id in parent_distro_ids:
                    new_owner = parent_ps.owner
                else:
                    new_owner = self.distroseries.owner
                child_ps = getUtility(IPackagesetSet).new(
                    parent_ps.name, parent_ps.description,
                    new_owner, distroseries=self.distroseries,
                    related_set=parent_ps)
            self._store.execute("""
                INSERT INTO Archivepermission
                (person, permission, archive, packageset, explicit)
                SELECT person, permission, %s, %s, explicit
                FROM Archivepermission WHERE packageset = %s
                """ % sqlvalues(
                    self.distroseries.main_archive, child_ps.id,
                    parent_ps.id))
            parent_to_child[parent_ps] = child_ps
        # Copy the relations between sets, and the contents.
        for old_series_ps, new_series_ps in parent_to_child.items():
            old_series_sets = old_series_ps.setsIncluded(
                direct_inclusion=True)
            for old_series_child in old_series_sets:
                new_series_ps.add(parent_to_child[old_series_child])
            new_series_ps.add(old_series_ps.sourcesIncluded(
                direct_inclusion=True))
