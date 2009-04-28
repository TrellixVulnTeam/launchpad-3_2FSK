# Copyright 2006 Canonical Ltd.  All rights reserved.
"""Test native publication workflow for Soyuz. """

import datetime
import operator
import os
import shutil
from StringIO import StringIO
import tempfile
import unittest

import pytz
from zope.component import getUtility

from canonical.archivepublisher.config import Config
from canonical.archivepublisher.diskpool import DiskPool
from canonical.config import config
from canonical.database.constants import UTC_NOW
from lp.soyuz.model.publishing import (
    SourcePackagePublishingHistory, SecureSourcePackagePublishingHistory,
    BinaryPackagePublishingHistory, SecureBinaryPackagePublishingHistory)
from lp.soyuz.model.processor import ProcessorFamily
from canonical.launchpad.interfaces.component import IComponentSet
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.interfaces.section import ISectionSet
from canonical.launchpad.webapp.interfaces import NotFoundError
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.sourcepackage import SourcePackageUrgency
from lp.registry.interfaces.sourcepackagename import ISourcePackageNameSet
from lp.soyuz.interfaces.binarypackagename import IBinaryPackageNameSet
from lp.soyuz.interfaces.binarypackagerelease import BinaryPackageFormat
from lp.soyuz.interfaces.build import BuildStatus
from lp.soyuz.interfaces.publishing import (
    PackagePublishingPocket, PackagePublishingPriority,
    PackagePublishingStatus)
from canonical.launchpad.scripts import FakeLogger
from canonical.launchpad.testing.factory import LaunchpadObjectFactory
from canonical.testing import LaunchpadZopelessLayer


class SoyuzTestPublisher:
    """Helper class able to publish coherent source and binaries in Soyuz."""

    def __init__(self):
        self.factory = LaunchpadObjectFactory()
        self.default_package_name = 'foo'

    def setUpDefaultDistroSeries(self, distroseries=None):
        """Set up a distroseries that will be used by default.

        This distro series is used to publish packages in, if you don't
        specify any when using the publishing methods.

        It also sets up a person that can act as the default uploader,
        and makes sure that the default package name exists in the
        database.

        :param distroseries: The `IDistroSeries` to use as default. If
            it's None, one will be created.
        :return: The `IDistroSeries` that got set as default.
        """
        if distroseries is None:
            distroseries = self.factory.makeDistroRelease()
        self.distroseries = distroseries
        # Set up a person that has a GPG key.
        self.person = getUtility(IPersonSet).getByName('name16')
        # Make sure the name exists in the database, to make it easier
        # to get packages from distributions and distro series.
        name_set = getUtility(ISourcePackageNameSet)
        name_set.getOrCreateByName(self.default_package_name)
        return self.distroseries

    def prepareBreezyAutotest(self):
        """Prepare ubuntutest/breezy-autotest for publications.

        It's also called during the normal test-case setUp.
        """
        self.ubuntutest = getUtility(IDistributionSet)['ubuntutest']
        self.breezy_autotest = self.ubuntutest['breezy-autotest']
        self.setUpDefaultDistroSeries(self.breezy_autotest)
        # Only create the DistroArchSeries needed if they do not exist yet.
        # This makes it easier to experiment at the python command line
        # (using "make harness").
        try:
            self.breezy_autotest_i386 = self.breezy_autotest['i386']
        except NotFoundError:
            self.breezy_autotest_i386 = self.breezy_autotest.newArch(
                'i386', ProcessorFamily.get(1), False, self.person,
                supports_virtualized=True)
        try:
            self.breezy_autotest_hppa = self.breezy_autotest['hppa']
        except NotFoundError:
            self.breezy_autotest_hppa = self.breezy_autotest.newArch(
                'hppa', ProcessorFamily.get(4), False, self.person)
        self.breezy_autotest.nominatedarchindep = self.breezy_autotest_i386
        fake_chroot = self.addMockFile('fake_chroot.tar.gz')
        self.breezy_autotest_i386.addOrUpdateChroot(fake_chroot)
        self.breezy_autotest_hppa.addOrUpdateChroot(fake_chroot)

    def addFakeChroots(self, distroseries=None):
        """Add fake chroots for all the architectures in distroseries."""
        if distroseries is None:
            distroseries = self.distroseries
        fake_chroot = self.addMockFile('fake_chroot.tar.gz')
        for arch in distroseries.architectures:
            arch.addOrUpdateChroot(fake_chroot)

    def regetBreezyAutotest(self): 
        self.ubuntutest = getUtility(IDistributionSet)['ubuntutest']
        self.breezy_autotest = self.ubuntutest['breezy-autotest']
        self.person = getUtility(IPersonSet).getByName('name16')
        self.breezy_autotest_i386 = self.breezy_autotest['i386']
        self.breezy_autotest_hppa = self.breezy_autotest['hppa']

    def addMockFile(self, filename, filecontent='nothing', restricted=False):
        """Add a mock file in Librarian.

        Returns a ILibraryFileAlias corresponding to the file uploaded.
        """
        library_file = getUtility(ILibraryFileAliasSet).create(
            filename, len(filecontent), StringIO(filecontent),
            'application/text', restricted=restricted)
        return library_file

    def addPackageUpload(self, archive, distroseries,
                         pocket=PackagePublishingPocket.RELEASE,
                         changes_file_name="foo_666_source.changes",
                         changes_file_content="fake changes file content"):
        signing_key =  self.person.gpgkeys[0]
        package_upload = distroseries.createQueueEntry(
            pocket, changes_file_name, changes_file_content, archive,
            signing_key)
        package_upload.setDone()
        return package_upload

    def getPubSource(self, sourcename=None, version='666', component='main',
                     filename=None, section='base',
                     filecontent='I do not care about sources.',
                     changes_file_content="Fake: fake changes file content",
                     status=PackagePublishingStatus.PENDING,
                     pocket=PackagePublishingPocket.RELEASE,
                     urgency=SourcePackageUrgency.LOW,
                     scheduleddeletiondate=None, dateremoved=None,
                     distroseries=None, archive=None, builddepends=None,
                     builddependsindep=None, architecturehintlist='all',
                     dsc_standards_version='3.6.2', dsc_format='1.0',
                     dsc_binaries='foo-bin', build_conflicts=None,
                     build_conflicts_indep=None,
                     dsc_maintainer_rfc822='Foo Bar <foo@bar.com>',
                     maintainer=None, date_uploaded=UTC_NOW):
        """Return a mock source publishing record."""
        if sourcename is None:
            sourcename = self.default_package_name
        spn = getUtility(ISourcePackageNameSet).getOrCreateByName(sourcename)

        component = getUtility(IComponentSet)[component]
        section = getUtility(ISectionSet)[section]

        if distroseries is None:
            distroseries = self.distroseries
        if archive is None:
            archive = distroseries.main_archive
        if maintainer is None:
            maintainer = self.person

        spr = distroseries.createUploadedSourcePackageRelease(
            sourcepackagename=spn,
            maintainer=maintainer,
            creator=self.person,
            component=component,
            section=section,
            urgency=urgency,
            version=version,
            builddepends=builddepends,
            builddependsindep=builddependsindep,
            build_conflicts=build_conflicts,
            build_conflicts_indep=build_conflicts_indep,
            architecturehintlist=architecturehintlist,
            changelog_entry=None,
            dsc=None,
            copyright='placeholder ...',
            dscsigningkey=self.person.gpgkeys[0],
            dsc_maintainer_rfc822=dsc_maintainer_rfc822,
            dsc_standards_version=dsc_standards_version,
            dsc_format=dsc_format,
            dsc_binaries=dsc_binaries,
            archive=archive, dateuploaded=date_uploaded)

        changes_file_name = "%s_%s_source.changes" % (sourcename, version)
        package_upload = self.addPackageUpload(
            archive, distroseries, pocket,
            changes_file_name=changes_file_name,
            changes_file_content=changes_file_content)
        package_upload.addSource(spr)

        if filename is None:
            filename = "%s_%s.dsc" % (sourcename, version)
        alias = self.addMockFile(
            filename, filecontent, restricted=archive.private)
        spr.addFile(alias)

        sspph = SecureSourcePackagePublishingHistory(
            distroseries=distroseries,
            sourcepackagerelease=spr,
            component=spr.component,
            section=spr.section,
            status=status,
            datecreated=date_uploaded,
            dateremoved=dateremoved,
            scheduleddeletiondate=scheduleddeletiondate,
            pocket=pocket,
            embargo=False,
            archive=archive)

        # SPPH and SSPPH IDs are the same, since they are SPPH is a SQLVIEW
        # of SSPPH and other useful attributes.
        return SourcePackagePublishingHistory.get(sspph.id)

    def getPubBinaries(self, binaryname='foo-bin', summary='Foo app is great',
                       description='Well ...\nit does nothing, though',
                       shlibdep=None, depends=None, recommends=None,
                       suggests=None, conflicts=None, replaces=None,
                       provides=None, pre_depends=None, enhances=None,
                       breaks=None, filecontent='bbbiiinnnaaarrryyy',
                       changes_file_content="Fake: fake changes file",
                       status=PackagePublishingStatus.PENDING,
                       pocket=PackagePublishingPocket.RELEASE,
                       format=BinaryPackageFormat.DEB,
                       scheduleddeletiondate=None, dateremoved=None,
                       distroseries=None,
                       archive=None,
                       pub_source=None):
        """Return a list of binary publishing records."""
        if distroseries is None:
            distroseries = self.distroseries

        if archive is None:
            archive = distroseries.main_archive

        if pub_source is None:
            sourcename = "%s" % binaryname.split('-')[0]
            pub_source = self.getPubSource(
                sourcename=sourcename, status=status, pocket=pocket,
                archive=archive, distroseries=distroseries)
        else:
            archive = pub_source.archive

        builds = pub_source.createMissingBuilds()
        published_binaries = []
        for build in builds:
            binarypackagerelease = self.uploadBinaryForBuild(
                build, binaryname, filecontent, summary, description,
                shlibdep, depends, recommends, suggests, conflicts, replaces,
                provides, pre_depends, enhances, breaks, format)
            pub_binaries = self.publishBinaryInArchive(
                binarypackagerelease, archive, status, pocket,
                scheduleddeletiondate, dateremoved)
            published_binaries.extend(pub_binaries)
            package_upload = self.addPackageUpload(
                archive, distroseries, pocket,
                changes_file_content=changes_file_content,
                changes_file_name='%s_%s_%s.changes' %
                    (binaryname, binarypackagerelease.version,
                     build.arch_tag))
            package_upload.addBuild(build)

        return sorted(
            published_binaries, key=operator.attrgetter('id'), reverse=True)

    def uploadBinaryForBuild(
        self, build, binaryname, filecontent="anything",
        summary="summary", description="description", shlibdep=None,
        depends=None, recommends=None, suggests=None, conflicts=None,
        replaces=None, provides=None, pre_depends=None, enhances=None,
        breaks=None, format=BinaryPackageFormat.DEB):
        """Return the corresponding `BinaryPackageRelease`."""
        sourcepackagerelease = build.sourcepackagerelease
        distroarchseries = build.distroarchseries
        architecturespecific = (
            not sourcepackagerelease.architecturehintlist == 'all')

        binarypackagename = getUtility(
            IBinaryPackageNameSet).getOrCreateByName(binaryname)

        binarypackagerelease = build.createBinaryPackageRelease(
            version=sourcepackagerelease.version,
            component=sourcepackagerelease.component,
            section=sourcepackagerelease.section,
            binarypackagename=binarypackagename,
            summary=summary,
            description=description,
            shlibdeps=shlibdep,
            depends=depends,
            recommends=recommends,
            suggests=suggests,
            conflicts=conflicts,
            replaces=replaces,
            provides=provides,
            pre_depends=pre_depends,
            enhances=enhances,
            breaks=breaks,
            essential=False,
            installedsize=100,
            architecturespecific=architecturespecific,
            binpackageformat=format,
            priority=PackagePublishingPriority.STANDARD)

        # Create the corresponding binary file.
        if architecturespecific:
            filearchtag = distroarchseries.architecturetag
        else:
            filearchtag = 'all'
        filename = '%s_%s_%s.%s' % (binaryname, sourcepackagerelease.version,
                                    filearchtag, format.name.lower())
        alias = self.addMockFile(
            filename, filecontent=filecontent,
            restricted=build.archive.private)
        binarypackagerelease.addFile(alias)

        build.buildstate = BuildStatus.FULLYBUILT

        return binarypackagerelease

    def publishBinaryInArchive(
        self, binarypackagerelease, archive,
        status=PackagePublishingStatus.PENDING,
        pocket=PackagePublishingPocket.RELEASE,
        scheduleddeletiondate=None, dateremoved=None):
        """Return the corresponding BinaryPackagePublishingHistory."""
        distroarchseries = binarypackagerelease.build.distroarchseries

        # Publish the binary.
        if binarypackagerelease.architecturespecific:
            archs = [distroarchseries]
        else:
            archs = distroarchseries.distroseries.architectures

        secure_pub_binaries = []
        for arch in archs:
            pub = SecureBinaryPackagePublishingHistory(
                distroarchseries=arch,
                binarypackagerelease=binarypackagerelease,
                component=binarypackagerelease.component,
                section=binarypackagerelease.section,
                priority=binarypackagerelease.priority,
                status=status,
                scheduleddeletiondate=scheduleddeletiondate,
                dateremoved=dateremoved,
                datecreated=UTC_NOW,
                pocket=pocket,
                embargo=False,
                archive=archive)
            if status == PackagePublishingStatus.PUBLISHED:
                pub.datepublished = UTC_NOW
            secure_pub_binaries.append(pub)

        return [BinaryPackagePublishingHistory.get(pub.id)
                for pub in secure_pub_binaries]


class TestNativePublishingBase(unittest.TestCase, SoyuzTestPublisher):
    layer = LaunchpadZopelessLayer
    dbuser = config.archivepublisher.dbuser

    def __init__(self, methodName='runTest'):
        unittest.TestCase.__init__(self, methodName=methodName)
        SoyuzTestPublisher.__init__(self)

    def setUp(self):
        """Setup a pool dir, the librarian, and instantiate the DiskPool."""
        self.layer.switchDbUser(config.archivepublisher.dbuser)
        self.prepareBreezyAutotest()
        self.config = Config(self.ubuntutest)
        self.config.setupArchiveDirs()
        self.pool_dir = self.config.poolroot
        self.temp_dir = self.config.temproot
        self.logger = FakeLogger()
        def message(self, prefix, *stuff, **kw):
            pass
        self.logger.message = message
        self.disk_pool = DiskPool(self.pool_dir, self.temp_dir, self.logger)

    def tearDown(self):
        """Tear down blows the pool dir away."""
        shutil.rmtree(self.config.distroroot)

    def getPubSource(self, *args, **kwargs):
        """Overrides `SoyuzTestPublisher.getPubSource`.

        Commits the transaction before returning, this way the rest of
        the test will immediately notice the just-created records.
        """
        source = SoyuzTestPublisher.getPubSource(self, *args, **kwargs)
        self.layer.commit()
        return source

    def getPubBinaries(self, *args, **kwargs):
        """Overrides `SoyuzTestPublisher.getPubBinaries`.

        Commits the transaction before returning, this way the rest of
        the test will immediately notice the just-created records.
        """
        binaries = SoyuzTestPublisher.getPubBinaries(self, *args, **kwargs)
        self.layer.commit()
        return binaries

    def checkSourcePublication(self, source, status):
        """Assert the source publications has the given status.

        Retrieve an up-to-date record corresponding to the given publication,
        check and return it.
        """
        fresh_source = SourcePackagePublishingHistory.get(source.id)
        self.assertEqual(
            fresh_source.status, status, "%s is not %s (%s)" % (
            fresh_source.displayname, status.name, source.status.name))
        return fresh_source

    def checkBinaryPublication(self, binary, status):
        """Assert the binary publication has the given status.

        Retrieve an up-to-date record corresponding to the given publication,
        check and return it.
        """
        fresh_binary = BinaryPackagePublishingHistory.get(binary.id)
        self.assertEqual(
            fresh_binary.status, status, "%s is not %s (%s)" % (
            fresh_binary.displayname, status.name, fresh_binary.status.name))
        return fresh_binary

    def checkBinaryPublications(self, binaries, status):
        """Assert the binary publications have the given status.

        See `checkBinaryPublication`.
        """
        fresh_binaries = []
        for bin in binaries:
            bin = self.checkBinaryPublication(bin, status)
            fresh_binaries.append(bin)
        return fresh_binaries

    def checkPublications(self, source, binaries, status):
        """Assert source and binary publications have in the given status.

        See `checkSourcePublication` and `checkBinaryPublications`.
        """
        self.checkSourcePublication(source, status)
        self.checkBinaryPublications(binaries, status)

    def getSecureSource(self, source):
        """Return the corresponding SecureSourcePackagePublishingHistory."""
        return SecureSourcePackagePublishingHistory.get(source.id)

    def getSecureBinary(self, binary):
        """Return the corresponding SecureBinaryPackagePublishingHistory."""
        return SecureBinaryPackagePublishingHistory.get(binary.id)

    def checkPastDate(self, date, lag=None):
        """Assert given date is older than 'now'.

        Optionally the user can pass a 'lag' which will be added to 'now'
        before comparing.
        """
        UTC = pytz.timezone("UTC")
        limit = datetime.datetime.now(UTC)
        if lag is not None:
            limit = limit + lag
        self.assertTrue(date < limit, "%s >= %s" % (date, limit))


class TestNativePublishing(TestNativePublishingBase):

    def testPublish(self):
        """Test publishOne in normal conditions (new file)."""
        pub_source = self.getPubSource(filecontent='Hello world')
        pub_source.publish(self.disk_pool, self.logger)
        self.layer.commit()

        pub_source.sync()
        self.assertEqual(pub_source.status, PackagePublishingStatus.PUBLISHED)
        foo_name = "%s/main/f/foo/foo_666.dsc" % self.pool_dir
        self.assertEqual(open(foo_name).read().strip(), 'Hello world')

    def testPublishingOverwriteFileInPool(self):
        """Test if publishOne refuses to overwrite a file in pool.

        Check if it also keeps the original file content.
        It's done by publishing 'foo' by-hand and ensuring it
        has a special content, then publish 'foo' again, via publisher,
        and finally check one of the 'foo' files content.
        """
        foo_path = os.path.join(self.pool_dir, 'main', 'f', 'foo')
        os.makedirs(foo_path)
        foo_dsc_path = os.path.join(foo_path, 'foo_666.dsc')
        foo_dsc = open(foo_dsc_path, 'w')
        foo_dsc.write('Hello world')
        foo_dsc.close()

        pub_source = self.getPubSource(filecontent="Something")
        pub_source.publish(self.disk_pool, self.logger)
        self.layer.commit()
        self.assertEqual(
            pub_source.status,PackagePublishingStatus.PENDING)
        self.assertEqual(open(foo_dsc_path).read().strip(), 'Hello world')

    def testPublishingDifferentContents(self):
        """Test if publishOne refuses to overwrite its own publication."""
        pub_source = self.getPubSource(filecontent='foo is happy')
        pub_source.publish(self.disk_pool, self.logger)
        self.layer.commit()

        foo_name = "%s/main/f/foo/foo_666.dsc" % self.pool_dir
        pub_source.sync()
        self.assertEqual(
            pub_source.status, PackagePublishingStatus.PUBLISHED)
        self.assertEqual(open(foo_name).read().strip(), 'foo is happy')

        # try to publish 'foo' again with a different content, it
        # raises internally and keeps the files with the original
        # content.
        pub_source2 = self.getPubSource(filecontent='foo is depressing')
        pub_source2.publish(self.disk_pool, self.logger)
        self.layer.commit()

        pub_source2.sync()
        self.assertEqual(
            pub_source2.status, PackagePublishingStatus.PENDING)
        self.assertEqual(open(foo_name).read().strip(), 'foo is happy')

    def testPublishingAlreadyInPool(self):
        """Test if publishOne works if file is already in Pool.

        It should identify that the file has the same content and
        mark it as PUBLISHED.
        """
        pub_source = self.getPubSource(
            sourcename='bar', filecontent='bar is good')
        pub_source.publish(self.disk_pool, self.logger)
        self.layer.commit()
        bar_name = "%s/main/b/bar/bar_666.dsc" % self.pool_dir
        self.assertEqual(open(bar_name).read().strip(), 'bar is good')
        pub_source.sync()
        self.assertEqual(
            pub_source.status, PackagePublishingStatus.PUBLISHED)

        pub_source2 = self.getPubSource(
            sourcename='bar', filecontent='bar is good')
        pub_source2.publish(self.disk_pool, self.logger)
        self.layer.commit()
        pub_source2.sync()
        self.assertEqual(
            pub_source2.status, PackagePublishingStatus.PUBLISHED)

    def testPublishingSymlink(self):
        """Test if publishOne moving publication between components.

        After check if the pool file contents as the same, it should
        create a symlink in the new pointing to the original file.
        """
        content = 'am I a file or a symbolic link ?'
        # publish sim.dsc in main and re-publish in universe
        pub_source = self.getPubSource(
            sourcename='sim', filecontent=content)
        pub_source2 = self.getPubSource(
            sourcename='sim', component='universe', filecontent=content)
        pub_source.publish(self.disk_pool, self.logger)
        pub_source2.publish(self.disk_pool, self.logger)
        self.layer.commit()

        pub_source.sync()
        pub_source2.sync()
        self.assertEqual(
            pub_source.status, PackagePublishingStatus.PUBLISHED)
        self.assertEqual(
            pub_source2.status, PackagePublishingStatus.PUBLISHED)

        # check the resulted symbolic link
        sim_universe = "%s/universe/s/sim/sim_666.dsc" % self.pool_dir
        self.assertEqual(
            os.readlink(sim_universe), '../../../main/s/sim/sim_666.dsc')

        # if the contexts don't match it raises, so the publication
        # remains pending.
        pub_source3 = self.getPubSource(
            sourcename='sim', component='restricted',
            filecontent='It is all my fault')
        pub_source3.publish(self.disk_pool, self.logger)
        self.layer.commit()

        pub_source3.sync()
        self.assertEqual(
            pub_source3.status, PackagePublishingStatus.PENDING)

    def testPublishInAnotherArchive(self):
        """Publication in another archive

        Basically test if publishing records target to other archive
        than Distribution.main_archive work as expected
        """
        cprov = getUtility(IPersonSet).getByName('cprov')
        test_pool_dir = tempfile.mkdtemp()
        test_temp_dir = tempfile.mkdtemp()
        test_disk_pool = DiskPool(test_pool_dir, test_temp_dir, self.logger)

        pub_source = self.getPubSource(
            sourcename="foo", filecontent='Am I a PPA Record ?',
            archive=cprov.archive)
        pub_source.publish(test_disk_pool, self.logger)
        self.layer.commit()

        pub_source.sync()
        self.assertEqual(pub_source.status, PackagePublishingStatus.PUBLISHED)
        self.assertEqual(pub_source.sourcepackagerelease.upload_archive,
                         cprov.archive)
        foo_name = "%s/main/f/foo/foo_666.dsc" % test_pool_dir
        self.assertEqual(open(foo_name).read().strip(), 'Am I a PPA Record ?')

        # Remove locally created dir.
        shutil.rmtree(test_pool_dir)
        shutil.rmtree(test_temp_dir)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
