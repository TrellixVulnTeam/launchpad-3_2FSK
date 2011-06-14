# Copyright 2010-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the initialise_distroseries script machinery."""

__metaclass__ = type

import os
import subprocess
import sys

from testtools.content import Content
from testtools.content_type import UTF8_TEXT
import transaction
from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.interfaces.lpstorm import IStore
from canonical.testing.layers import LaunchpadZopelessLayer
from lp.buildmaster.enums import BuildStatus
from lp.registry.interfaces.distroseriesparent import IDistroSeriesParentSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.soyuz.enums import SourcePackageFormat
from lp.soyuz.interfaces.archivepermission import IArchivePermissionSet
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.packageset import (
    IPackagesetSet,
    NoSuchPackageSet,
    )
from lp.soyuz.interfaces.publishing import PackagePublishingStatus
from lp.soyuz.interfaces.sourcepackageformat import (
    ISourcePackageFormatSelectionSet,
    )
from lp.soyuz.model.component import ComponentSelection
from lp.soyuz.model.distroarchseries import DistroArchSeries
from lp.soyuz.model.section import SectionSelection
from lp.soyuz.scripts.initialise_distroseries import (
    InitialisationError,
    InitialiseDistroSeries,
    )
from lp.testing import TestCaseWithFactory


class TestInitialiseDistroSeries(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setupParent(self, packages=None, format_selection=None):
        parent = self.factory.makeDistroSeries()
        parent_das = self.factory.makeDistroArchSeries(distroseries=parent)
        lf = self.factory.makeLibraryFileAlias()
        transaction.commit()
        parent_das.addOrUpdateChroot(lf)
        parent_das.supports_virtualized = True
        parent.nominatedarchindep = parent_das
        if format_selection is None:
            format_selection = SourcePackageFormat.FORMAT_1_0
        getUtility(ISourcePackageFormatSelectionSet).add(
            parent, format_selection)
        parent.backports_not_automatic = True
        self._populate_parent(parent, parent_das, packages)
        return parent, parent_das

    def _populate_parent(self, parent, parent_das, packages=None):
        if packages is None:
            packages = {'udev': '0.1-1', 'libc6': '2.8-1',
                'postgresql': '9.0-1', 'chromium': '3.6'}
        for package in packages.keys():
            spn = self.factory.getOrMakeSourcePackageName(package)
            spph = self.factory.makeSourcePackagePublishingHistory(
                sourcepackagename=spn, version=packages[package],
                distroseries=parent,
                pocket=PackagePublishingPocket.RELEASE,
                status=PackagePublishingStatus.PUBLISHED)
            status = BuildStatus.FULLYBUILT
            if package is 'chromium':
                status = BuildStatus.FAILEDTOBUILD
            bpn = self.factory.getOrMakeBinaryPackageName(package)
            build = self.factory.makeBinaryPackageBuild(
                source_package_release=spph.sourcepackagerelease,
                distroarchseries=parent_das,
                status=status)
            bpr = self.factory.makeBinaryPackageRelease(
                binarypackagename=bpn, build=build,
                version=packages[package])
            if package is not 'chromium':
                self.factory.makeBinaryPackagePublishingHistory(
                    binarypackagerelease=bpr,
                    distroarchseries=parent_das,
                    pocket=PackagePublishingPocket.RELEASE,
                    status=PackagePublishingStatus.PUBLISHED)

    def test_failure_for_already_released_distroseries(self):
        # Initialising a distro series that has already been used will
        # error.
        self.parent, self.parent_das = self.setupParent()
        child = self.factory.makeDistroSeries()
        self.factory.makeDistroArchSeries(distroseries=child)
        ids = InitialiseDistroSeries(child, [self.parent.id])
        self.assertRaisesWithContent(
            InitialisationError,
            "Can not copy distroarchseries from parent, there are already "
            "distroarchseries(s) initialised for this series.", ids.check)

    def test_failure_with_pending_builds(self):
        # If the parent series has pending builds, and the child is a series
        # of the same distribution (which means they share an archive), we
        # can't initialise.
        self.parent, self.parent_das = self.setupParent()
        source = self.factory.makeSourcePackagePublishingHistory(
            distroseries=self.parent,
            pocket=PackagePublishingPocket.RELEASE)
        source.createMissingBuilds()
        child = self.factory.makeDistroSeries(
            distribution=self.parent.parent, previous_series=self.parent)
        ids = InitialiseDistroSeries(child, [self.parent.id])
        self.assertRaisesWithContent(
            InitialisationError, "Parent series has pending builds.",
            ids.check)

    def test_success_with_pending_builds(self):
        # If the parent series has pending builds, and the child's
        # distribution is different, we can initialise.
        self.parent, self.parent_das = self.setupParent()
        source = self.factory.makeSourcePackagePublishingHistory(
            distroseries=self.parent,
            pocket=PackagePublishingPocket.RELEASE)
        source.createMissingBuilds()
        child = self._fullInitialise([self.parent])
        self.assertDistroSeriesInitialisedCorrectly(
            child, self.parent, self.parent_das)

    def test_failure_with_queue_items(self):
        # If the parent series has items in its queues, such as NEW and
        # UNAPPROVED, we can't initialise.
        self.parent, self.parent_das = self.setupParent()
        self.parent.createQueueEntry(
            PackagePublishingPocket.RELEASE, self.parent.main_archive,
            'foo.changes', 'bar')
        child = self.factory.makeDistroSeries()
        ids = InitialiseDistroSeries(child, [self.parent.id])
        self.assertRaisesWithContent(
            InitialisationError, "Parent series queues are not empty.",
            ids.check)

    def assertDistroSeriesInitialisedCorrectly(self, child, parent,
                                               parent_das):
        # Check that 'udev' has been copied correctly.
        parent_udev_pubs = parent.getPublishedSources('udev')
        child_udev_pubs = child.getPublishedSources('udev')
        self.assertEqual(
            parent_udev_pubs.count(), child_udev_pubs.count())
        parent_arch_udev_pubs = parent[
            parent_das.architecturetag].getReleasedPackages('udev')
        child_arch_udev_pubs = child[
            parent_das.architecturetag].getReleasedPackages('udev')
        self.assertEqual(
            len(parent_arch_udev_pubs), len(child_arch_udev_pubs))
        # And the binary package, and linked source package look fine too.
        udev_bin = child_arch_udev_pubs[0].binarypackagerelease
        self.assertEqual(udev_bin.title, u'udev-0.1-1')
        self.assertEqual(
            udev_bin.build.title,
            u'%s build of udev 0.1-1 in %s %s RELEASE' % (
                parent_das.architecturetag, parent.parent.name,
                parent.name))
        udev_src = udev_bin.build.source_package_release
        self.assertEqual(udev_src.title, u'udev - 0.1-1')
        # The build of udev 0.1-1 has been copied across.
        child_udev = udev_src.getBuildByArch(
            child[parent_das.architecturetag], child.main_archive)
        parent_udev = udev_src.getBuildByArch(
            parent[parent_das.architecturetag],
            parent.main_archive)
        self.assertEqual(parent_udev.id, child_udev.id)
        # We also inherit the permitted source formats from our parent.
        self.assertTrue(
            child.isSourcePackageFormatPermitted(
            SourcePackageFormat.FORMAT_1_0))
        # Other configuration bits are copied too.
        self.assertTrue(child.backports_not_automatic)

    def _fullInitialise(self, parents, child=None, previous_series=None,
                        arches=(), packagesets=(), rebuild=False,
                        distribution=None, overlays=(),
                        overlay_pockets=(), overlay_components=()):
        if child is None:
            child = self.factory.makeDistroSeries(
                distribution=distribution, previous_series=previous_series)
        ids = InitialiseDistroSeries(
            child, [parent.id for parent in parents], arches, packagesets,
            rebuild, overlays, overlay_pockets, overlay_components)
        ids.check()
        ids.initialise()
        return child

    def test_initialise(self):
        # Test a full initialise with no errors.
        self.parent, self.parent_das = self.setupParent()
        child = self._fullInitialise([self.parent])
        self.assertDistroSeriesInitialisedCorrectly(
            child, self.parent, self.parent_das)

    def test_initialise_only_one_das(self):
        # Test a full initialise with no errors, but only copy i386 to
        # the child.
        self.parent, self.parent_das = self.setupParent()
        self.factory.makeDistroArchSeries(distroseries=self.parent)
        child = self._fullInitialise(
            [self.parent],
            arches=[self.parent_das.architecturetag])
        self.assertDistroSeriesInitialisedCorrectly(
            child, self.parent, self.parent_das)
        das = list(IStore(DistroArchSeries).find(
            DistroArchSeries, distroseries=child))
        self.assertEqual(len(das), 1)
        self.assertEqual(
            das[0].architecturetag, self.parent_das.architecturetag)

    def test_copying_packagesets(self):
        # If a parent series has packagesets, we should copy them.
        self.parent, self.parent_das = self.setupParent()
        uploader = self.factory.makePerson()
        test1 = getUtility(IPackagesetSet).new(
            u'test1', u'test 1 packageset', self.parent.owner,
            distroseries=self.parent)
        test2 = getUtility(IPackagesetSet).new(
            u'test2', u'test 2 packageset', self.parent.owner,
            distroseries=self.parent)
        test3 = getUtility(IPackagesetSet).new(
            u'test3', u'test 3 packageset', self.parent.owner,
            distroseries=self.parent, related_set=test2)
        test1.addSources('udev')
        getUtility(IArchivePermissionSet).newPackagesetUploader(
            self.parent.main_archive, uploader, test1)
        child = self._fullInitialise([self.parent])
        # We can fetch the copied sets from the child.
        child_test1 = getUtility(IPackagesetSet).getByName(
            u'test1', distroseries=child)
        child_test2 = getUtility(IPackagesetSet).getByName(
            u'test2', distroseries=child)
        child_test3 = getUtility(IPackagesetSet).getByName(
            u'test3', distroseries=child)
        # And we can see they are exact copies, with the related_set for the
        # copies pointing to the packageset in the parent.
        self.assertEqual(test1.description, child_test1.description)
        self.assertEqual(test2.description, child_test2.description)
        self.assertEqual(test3.description, child_test3.description)
        self.assertEqual(child_test1.relatedSets().one(), test1)
        self.assertEqual(
            list(child_test2.relatedSets()),
            [test2, test3, child_test3])
        self.assertEqual(
            list(child_test3.relatedSets()),
            [test2, child_test2, test3])
        # The contents of the packagesets will have been copied.
        child_srcs = child_test1.getSourcesIncluded(
            direct_inclusion=True)
        parent_srcs = test1.getSourcesIncluded(direct_inclusion=True)
        self.assertEqual(parent_srcs, child_srcs)
        # The uploader can also upload to the new distroseries.
        self.assertTrue(
            getUtility(IArchivePermissionSet).isSourceUploadAllowed(
                self.parent.main_archive, 'udev', uploader,
                distroseries=self.parent))
        self.assertTrue(
            getUtility(IArchivePermissionSet).isSourceUploadAllowed(
                child.main_archive, 'udev', uploader,
                distroseries=child))

    def test_packageset_owner_preserved_within_distro(self):
        # When initialising a new series within a distro, the copied
        # packagesets have ownership preserved.
        self.parent, self.parent_das = self.setupParent(packages={})
        ps_owner = self.factory.makePerson()
        getUtility(IPackagesetSet).new(
            u'ps', u'packageset', ps_owner, distroseries=self.parent)
        child = self._fullInitialise(
            [self.parent], distribution=self.parent.distribution)
        child_ps = getUtility(IPackagesetSet).getByName(
            u'ps', distroseries=child)
        self.assertEqual(ps_owner, child_ps.owner)

    def test_packageset_owner_not_preserved_cross_distro(self):
        # In the case of a cross-distro initialisation, the new
        # packagesets are owned by the new distro owner.
        self.parent, self.parent_das = self.setupParent()
        getUtility(IPackagesetSet).new(
            u'ps', u'packageset', self.factory.makePerson(),
            distroseries=self.parent)
        child = self._fullInitialise([self.parent])
        child_ps = getUtility(IPackagesetSet).getByName(
            u'ps', distroseries=child)
        self.assertEqual(child.owner, child_ps.owner)

    def test_copy_limit_packagesets(self):
        # If a parent series has packagesets, we can decide which ones we
        # want to copy.
        self.parent, self.parent_das = self.setupParent()
        test1 = getUtility(IPackagesetSet).new(
            u'test1', u'test 1 packageset', self.parent.owner,
            distroseries=self.parent)
        getUtility(IPackagesetSet).new(
            u'test2', u'test 2 packageset', self.parent.owner,
            distroseries=self.parent)
        packages = ('udev', 'chromium', 'libc6')
        for pkg in packages:
            test1.addSources(pkg)
        packageset1 = getUtility(IPackagesetSet).getByName(
            u'test1', distroseries=self.parent)
        child = self._fullInitialise(
            [self.parent], packagesets=(str(packageset1.id),))
        child_test1 = getUtility(IPackagesetSet).getByName(
            u'test1', distroseries=child)
        self.assertEqual(test1.description, child_test1.description)
        self.assertRaises(
            NoSuchPackageSet, getUtility(IPackagesetSet).getByName,
                u'test2', distroseries=child)
        parent_srcs = test1.getSourcesIncluded(direct_inclusion=True)
        child_srcs = child_test1.getSourcesIncluded(
            direct_inclusion=True)
        self.assertEqual(parent_srcs, child_srcs)
        child.updatePackageCount()
        self.assertEqual(child.sourcecount, len(packages))
        self.assertEqual(child.binarycount, 2)  # Chromium is FTBFS

    def test_rebuild_flag(self):
        # No binaries will get copied if we specify rebuild=True.
        self.parent, self.parent_das = self.setupParent()
        self.parent.updatePackageCount()
        child = self._fullInitialise([self.parent], rebuild=True)
        child.updatePackageCount()
        builds = child.getBuildRecords(
            build_state=BuildStatus.NEEDSBUILD,
            pocket=PackagePublishingPocket.RELEASE)
        self.assertEqual(self.parent.sourcecount, child.sourcecount)
        self.assertEqual(child.binarycount, 0)
        self.assertEqual(builds.count(), self.parent.sourcecount)

    def test_limit_packagesets_rebuild_and_one_das(self):
        # We can limit the source packages copied, and only builds
        # for the copied source will be created.
        self.parent, self.parent_das = self.setupParent()
        test1 = getUtility(IPackagesetSet).new(
            u'test1', u'test 1 packageset', self.parent.owner,
            distroseries=self.parent)
        getUtility(IPackagesetSet).new(
            u'test2', u'test 2 packageset', self.parent.owner,
            distroseries=self.parent)
        packages = ('udev', 'chromium')
        for pkg in packages:
            test1.addSources(pkg)
        self.factory.makeDistroArchSeries(distroseries=self.parent)
        child = self._fullInitialise(
            [self.parent],
            arches=[self.parent_das.architecturetag],
            packagesets=(str(test1.id),), rebuild=True)
        child.updatePackageCount()
        builds = child.getBuildRecords(
            build_state=BuildStatus.NEEDSBUILD,
            pocket=PackagePublishingPocket.RELEASE)
        self.assertEqual(child.sourcecount, len(packages))
        self.assertEqual(child.binarycount, 0)
        self.assertEqual(builds.count(), len(packages))
        das = list(IStore(DistroArchSeries).find(
            DistroArchSeries, distroseries=child))
        self.assertEqual(len(das), 1)
        self.assertEqual(
            das[0].architecturetag, self.parent_das.architecturetag)

    def test_do_not_copy_disabled_dases(self):
        # DASes that are disabled in the parent will not be copied.
        self.parent, self.parent_das = self.setupParent()
        ppc_das = self.factory.makeDistroArchSeries(
            distroseries=self.parent)
        ppc_das.enabled = False
        child = self._fullInitialise([self.parent])
        das = list(IStore(DistroArchSeries).find(
            DistroArchSeries, distroseries=child))
        self.assertEqual(len(das), 1)
        self.assertEqual(
            das[0].architecturetag, self.parent_das.architecturetag)

    def test_script(self):
        # Do an end-to-end test using the command-line tool.
        self.parent, self.parent_das = self.setupParent()
        uploader = self.factory.makePerson()
        test1 = getUtility(IPackagesetSet).new(
            u'test1', u'test 1 packageset', self.parent.owner,
            distroseries=self.parent)
        test1.addSources('udev')
        getUtility(IArchivePermissionSet).newPackagesetUploader(
            self.parent.main_archive, uploader, test1)
        child = self.factory.makeDistroSeries(previous_series=self.parent)
        # Create an initialized series in the distribution.
        other_series = self.factory.makeDistroSeries(
            distribution=child.parent)
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=other_series)
        transaction.commit()
        ifp = os.path.join(
            config.root, 'scripts', 'ftpmaster-tools',
            'initialise-from-parent.py')
        process = subprocess.Popen(
            [sys.executable, ifp, "-vv", "-d", child.parent.name,
            child.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        self.addDetail("stdout", Content(UTF8_TEXT, lambda: stdout))
        self.addDetail("stderr", Content(UTF8_TEXT, lambda: stderr))
        self.assertEqual(process.returncode, 0)
        self.assertTrue(
            "DEBUG   Committing transaction." in stderr.split('\n'))
        transaction.commit()
        self.assertDistroSeriesInitialisedCorrectly(
            child, self.parent, self.parent_das)

    def test_is_initialized(self):
        # At the end of the initialisation, the distroseriesparent is marked
        # as 'initialised'.
        self.parent, self.parent_das = self.setupParent()
        child = self._fullInitialise([self.parent], rebuild=True, overlays=())
        dsp_set = getUtility(IDistroSeriesParentSet)
        distroseriesparent = dsp_set.getByDerivedAndParentSeries(
            child, self.parent)

        self.assertTrue(distroseriesparent.initialized)

    def test_no_overlays(self):
        # Without the overlay parameter, no overlays are created.
        self.parent, self.parent_das = self.setupParent()
        child = self._fullInitialise([self.parent], rebuild=True, overlays=[])
        dsp_set = getUtility(IDistroSeriesParentSet)
        distroseriesparent = dsp_set.getByDerivedAndParentSeries(
            child, self.parent)

        self.assertFalse(distroseriesparent.is_overlay)

    def test_setup_overlays(self):
        # If the overlay parameter is passed, overlays are properly setup.
        self.parent1, unused = self.setupParent()
        self.parent2, unused = self.setupParent()

        overlays = [False, True]
        overlay_pockets = [None, 'Updates']
        overlay_components = [None, 'universe']
        child = self._fullInitialise(
            [self.parent1, self.parent2], rebuild=True,
            overlays=overlays,
            overlay_pockets=overlay_pockets,
            overlay_components=overlay_components)
        dsp_set = getUtility(IDistroSeriesParentSet)
        distroseriesparent1 = dsp_set.getByDerivedAndParentSeries(
            child, self.parent1)
        distroseriesparent2 = dsp_set.getByDerivedAndParentSeries(
            child, self.parent2)

        self.assertFalse(distroseriesparent1.is_overlay)
        self.assertTrue(distroseriesparent2.is_overlay)
        self.assertEqual(
            getUtility(IComponentSet)['universe'],
            distroseriesparent2.component)
        self.assertEqual(
            PackagePublishingPocket.UPDATES, distroseriesparent2.pocket)

    def test_multiple_parents_initialize(self):
        self.parent, self.parent_das = self.setupParent()
        self.parent2, self.parent_das2 = self.setupParent(
            packages={'alpha': '0.1-1'})
        child = self._fullInitialise([self.parent, self.parent2])
        self.assertDistroSeriesInitialisedCorrectly(
            child, self.parent, self.parent_das)

    def test_multiple_parents_ordering(self):
        # The parents' order is stored.
        self.parent1, self.parent_das = self.setupParent()
        self.parent2, self.parent_das2 = self.setupParent()
        self.parent3, self.parent_das3 = self.setupParent()
        child = self._fullInitialise(
            [self.parent1, self.parent3, self.parent2])
        dsp_set = getUtility(IDistroSeriesParentSet)
        distroseriesparent1 = dsp_set.getByDerivedAndParentSeries(
            child, self.parent1)
        distroseriesparent2 = dsp_set.getByDerivedAndParentSeries(
            child, self.parent2)
        distroseriesparent3 = dsp_set.getByDerivedAndParentSeries(
            child, self.parent3)

        self.assertContentEqual(
            [self.parent1, self.parent3, self.parent2],
            child.getParentSeries())
        self.assertEqual(1, distroseriesparent1.ordering)
        self.assertEqual(3, distroseriesparent2.ordering)
        self.assertEqual(2, distroseriesparent3.ordering)

    def test_multiple_parent_packagesets_merge(self):
        # Identical packagesets from the parents are merged as one
        # packageset in the child.
        self.parent1, self.parent_das1 = self.setupParent()
        self.parent2, self.parent_das2 = self.setupParent()
        uploader1 = self.factory.makePerson()
        uploader2 = self.factory.makePerson()
        test1_parent1 = getUtility(IPackagesetSet).new(
            u'test1', u'test 1 packageset', self.parent1.owner,
            distroseries=self.parent1)
        test1_parent2 = getUtility(IPackagesetSet).new(
            u'test1', u'test 1 packageset', self.parent2.owner,
            distroseries=self.parent2)
        test1_parent1.addSources('chromium')
        test1_parent1.addSources('udev')
        test1_parent2.addSources('udev')
        test1_parent2.addSources('libc6')
        getUtility(IArchivePermissionSet).newPackagesetUploader(
            self.parent1.main_archive, uploader1, test1_parent1)
        getUtility(IArchivePermissionSet).newPackagesetUploader(
            self.parent2.main_archive, uploader2, test1_parent2)
        child = self._fullInitialise([self.parent1, self.parent2])

        # In the child, the identical packagesets are merged into one.
        child_test1 = getUtility(IPackagesetSet).getByName(
            u'test1', distroseries=child)
        child_srcs = child_test1.getSourcesIncluded(
            direct_inclusion=True)
        parent1_srcs = test1_parent1.getSourcesIncluded(direct_inclusion=True)
        parent2_srcs = test1_parent2.getSourcesIncluded(direct_inclusion=True)
        self.assertContentEqual(
            set(parent1_srcs).union(set(parent2_srcs)),
            child_srcs)
        # The uploaders can also upload to the new distroseries.
        self.assertTrue(
            getUtility(IArchivePermissionSet).isSourceUploadAllowed(
                self.parent1.main_archive, 'udev', uploader1,
                distroseries=self.parent1))
        self.assertTrue(
            getUtility(IArchivePermissionSet).isSourceUploadAllowed(
                child.main_archive, 'udev', uploader1,
                distroseries=child))
        self.assertTrue(
            getUtility(IArchivePermissionSet).isSourceUploadAllowed(
                self.parent2.main_archive, 'libc6', uploader2,
                distroseries=self.parent2))
        self.assertTrue(
            getUtility(IArchivePermissionSet).isSourceUploadAllowed(
                child.main_archive, 'libc6', uploader2,
                distroseries=child))

    def test_multiple_parents_format_selection_union(self):
        # The format selection for the derived series is the union of
        # the format selections of the parents.
        format1 = SourcePackageFormat.FORMAT_1_0
        format2 = SourcePackageFormat.FORMAT_3_0_QUILT
        self.parent1, notused = self.setupParent(format_selection=format1)
        self.parent2, notused = self.setupParent(format_selection=format2)
        child = self._fullInitialise([self.parent1, self.parent2])

        self.assertTrue(child.isSourcePackageFormatPermitted(format1))
        self.assertTrue(child.isSourcePackageFormatPermitted(format2))

    def test_multiple_parents_component_merge(self):
        # The components from the parents are merged to create the
        # child's components.
        self.comp1 = self.factory.makeComponent()
        self.comp2 = self.factory.makeComponent()
        self.parent1, notused = self.setupParent()
        self.parent2, notused = self.setupParent()
        ComponentSelection(distroseries=self.parent1, component=self.comp1)
        ComponentSelection(distroseries=self.parent2, component=self.comp1)
        ComponentSelection(distroseries=self.parent2, component=self.comp2)
        child = self._fullInitialise([self.parent1, self.parent2])

        self.assertContentEqual(
            [self.comp1, self.comp2],
            child.components)

    def test_multiple_parents_section_merge(self):
        # The sections from the parents are merged to create the child's
        # sections.
        self.section1 = self.factory.makeSection()
        self.section2 = self.factory.makeSection()
        self.parent1, notused = self.setupParent()
        self.parent2, notused = self.setupParent()
        SectionSelection(distroseries=self.parent1, section=self.section1)
        SectionSelection(distroseries=self.parent2, section=self.section1)
        SectionSelection(distroseries=self.parent2, section=self.section2)
        child = self._fullInitialise([self.parent1, self.parent2])

        self.assertContentEqual(
            [self.section1, self.section2],
            child.sections)

    def test_multiple_parents_same_packaging(self):
        # If the same packaging exists different parents, the packaging
        # in the first parent takes precedence.
        self.parent1, self.parent_das1 = self.setupParent(
            packages={'package': '0.3-1'})
        self.parent2, self.parent_das2 = self.setupParent(
            packages={'package': '0.1-1'})
        sourcepackagename = self.factory.getOrMakeSourcePackageName('package')
        packaging1 = self.factory.makePackagingLink(
            distroseries=self.parent1, sourcepackagename=sourcepackagename)
        self.factory.makePackagingLink(
            distroseries=self.parent2, sourcepackagename=sourcepackagename)
        child = self._fullInitialise([self.parent1, self.parent2])
        productseries1 = packaging1.productseries
        child_packagings = productseries1.getPackagingInDistribution(
            child.distribution)

        self.assertEquals(1, len(child_packagings))
        self.assertEquals(
            packaging1.owner,
            child_packagings[0].owner)

    def test_multiple_parents_same_package(self):
        # If the same package is published in different parents, the package
        # in the first parent takes precedence.
        self.parent1, self.parent_das1 = self.setupParent(
            packages={'package': '0.3-1'})
        self.parent2, self.parent_das2 = self.setupParent(
            packages={'package': '0.1-1'})
        child = self._fullInitialise([self.parent1, self.parent2])
        published_sources = child.main_archive.getPublishedSources()

        self.assertEquals(1, published_sources.count())
        self.assertEquals(
            u'0.3-1',
            published_sources[0].sourcepackagerelease.version)

    def setUpSeriesWithPreviousSeries(self, parent, previous_parents=(),
                                      publish_in_distribution=True):
        # Helper method to create a series within an initialized
        # distribution (i.e. that has an initialized series) with a
        # 'previous_series' with parents.

        # Create a previous_series derived from 2 parents.
        previous_series = self._fullInitialise(previous_parents)

        child = self.factory.makeDistroSeries(previous_series=previous_series)

        # Add a publishing in another series from this distro.
        other_series = self.factory.makeDistroSeries(
            distribution=child.distribution)
        if publish_in_distribution:
            self.factory.makeSourcePackagePublishingHistory(
                distroseries=other_series)

        return child

    def test_derive_from_previous_parents(self):
        # If the series to be initialized is in a distribution with
        # initialized series, the series is *derived* from
        # the previous_series' parents.
        previous_parent1, unused = self.setupParent(packages={u'p1': u'1.2'})
        previous_parent2, unused = self.setupParent(packages={u'p2': u'1.5'})
        parent, unused = self.setupParent()
        child = self.setUpSeriesWithPreviousSeries(
            parent=parent,
            previous_parents=[previous_parent1, previous_parent2])
        self._fullInitialise([parent], child=child)

        # The parent for the derived series is the distroseries given as
        # argument to InitializeSeries.
        self.assertContentEqual(
            [parent],
            child.getParentSeries())

        # The new series has been derived from previous_series.
        published_sources = child.main_archive.getPublishedSources(
            distroseries=child)
        self.assertEquals(2, published_sources.count())
        pub_sources = sorted(
            [(s.sourcepackagerelease.sourcepackagename.name,
              s.sourcepackagerelease.version)
                for s in published_sources])
        self.assertEquals(
            [(u'p1', u'1.2'), (u'p2', u'1.5')],
            pub_sources)

    def test_derive_from_previous_parents_empty_parents(self):
        # If an empty list is passed to InitialiseDistroSeries, the
        # parents of the previous series are used as parents.
        previous_parent1, unused = self.setupParent(packages={u'p1': u'1.2'})
        previous_parent2, unused = self.setupParent(packages={u'p2': u'1.5'})
        parent, unused = self.setupParent()
        child = self.setUpSeriesWithPreviousSeries(
            parent=parent,
            previous_parents=[previous_parent1, previous_parent2])
        # Initialize from an empty list of parents.
        self._fullInitialise([], child=child)

        self.assertContentEqual(
            [previous_parent1, previous_parent2],
            child.getParentSeries())

    def test_derive_empty_parents_distribution_not_initialized(self):
        # Initializing a series with an empty parent list if the series'
        # distribution has no initialized series triggers an error.
        parent, unused = self.setupParent()
        previous_parent1, unused = self.setupParent(packages={u'p1': u'1.2'})
        child = self.setUpSeriesWithPreviousSeries(
            parent=parent,
            previous_parents=[previous_parent1],
            publish_in_distribution=False)

        # Initialize from an empty list of parents.
        ids = InitialiseDistroSeries(child, [])
        self.assertRaisesWithContent(
            InitialisationError,
            ("Distroseries {child.name} cannot be initialized: "
             "No other series in the distribution is initialized "
             "and no parent was passed to the initilization method"
             ".").format(child=child),
             ids.check)
