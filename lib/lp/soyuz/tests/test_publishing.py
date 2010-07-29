# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test native publication workflow for Soyuz. """

import datetime
import operator
import os
import shutil
from StringIO import StringIO
import tempfile

import pytz
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.webapp.errorlog import ErrorReportingUtility
from canonical.launchpad.webapp.interfaces import NotFoundError
from canonical.testing import (
    DatabaseFunctionalLayer, LaunchpadZopelessLayer)
from lp.archivepublisher.config import Config
from lp.archivepublisher.diskpool import DiskPool
from lp.buildmaster.interfaces.buildbase import BuildStatus
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.sourcepackage import SourcePackageUrgency
from lp.registry.interfaces.sourcepackagename import ISourcePackageNameSet
from lp.soyuz.model.processor import ProcessorFamily
from lp.soyuz.model.publishing import (
    SourcePackagePublishingHistory, BinaryPackagePublishingHistory)
from lp.soyuz.interfaces.archive import ArchivePurpose
from lp.soyuz.interfaces.archivearch import IArchiveArchSet
from lp.soyuz.interfaces.binarypackagename import IBinaryPackageNameSet
from lp.soyuz.interfaces.binarypackagerelease import BinaryPackageFormat
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.section import ISectionSet
from lp.soyuz.interfaces.publishing import (
    IPublishingSet, PackagePublishingPriority, PackagePublishingStatus)
from lp.soyuz.interfaces.queue import PackageUploadStatus
from canonical.launchpad.scripts import FakeLogger
from lp.testing import TestCaseWithFactory
from lp.testing.factory import (
    LaunchpadObjectFactory, remove_security_proxy_and_shout_at_engineer)
from lp.testing.fakemethod import FakeMethod


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
                         changes_file_content="fake changes file content",
                         upload_status=PackageUploadStatus.DONE):
        signing_key = self.person.gpg_keys[0]
        package_upload = distroseries.createQueueEntry(
            pocket, changes_file_name, changes_file_content, archive,
            signing_key)

        status_to_method = {
            PackageUploadStatus.DONE: 'setDone',
            PackageUploadStatus.ACCEPTED: 'setAccepted',
            }
        naked_package_upload = remove_security_proxy_and_shout_at_engineer(
            package_upload)
        method = getattr(
            naked_package_upload, status_to_method[upload_status])
        method()

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
                     maintainer=None, creator=None, date_uploaded=UTC_NOW,
                     spr_only=False):
        """Return a mock source publishing record.

        if spr_only is specified, the source is not published and the
        sourcepackagerelease object is returned instead.
        """
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
        if creator is None:
            creator = self.person

        spr = distroseries.createUploadedSourcePackageRelease(
            sourcepackagename=spn,
            maintainer=maintainer,
            creator=creator,
            component=component,
            section=section,
            urgency=urgency,
            version=version,
            builddepends=builddepends,
            builddependsindep=builddependsindep,
            build_conflicts=build_conflicts,
            build_conflicts_indep=build_conflicts_indep,
            architecturehintlist=architecturehintlist,
            changelog=None,
            changelog_entry=None,
            dsc=None,
            copyright='placeholder ...',
            dscsigningkey=self.person.gpg_keys[0],
            dsc_maintainer_rfc822=dsc_maintainer_rfc822,
            dsc_standards_version=dsc_standards_version,
            dsc_format=dsc_format,
            dsc_binaries=dsc_binaries,
            archive=archive, dateuploaded=date_uploaded)

        changes_file_name = "%s_%s_source.changes" % (sourcename, version)
        if spr_only:
            upload_status = PackageUploadStatus.ACCEPTED
        else:
            upload_status = PackageUploadStatus.DONE
        package_upload = self.addPackageUpload(
            archive, distroseries, pocket,
            changes_file_name=changes_file_name,
            changes_file_content=changes_file_content,
            upload_status=upload_status)
        naked_package_upload = remove_security_proxy_and_shout_at_engineer(
            package_upload)
        naked_package_upload.addSource(spr)

        if filename is None:
            filename = "%s_%s.dsc" % (sourcename, version)
        alias = self.addMockFile(
            filename, filecontent, restricted=archive.private)
        spr.addFile(alias)

        if spr_only:
            return spr

        if status == PackagePublishingStatus.PUBLISHED:
            datepublished = UTC_NOW
        else:
            datepublished = None

        spph = SourcePackagePublishingHistory(
            distroseries=distroseries,
            sourcepackagerelease=spr,
            component=spr.component,
            section=spr.section,
            status=status,
            datecreated=date_uploaded,
            dateremoved=dateremoved,
            datepublished=datepublished,
            scheduleddeletiondate=scheduleddeletiondate,
            pocket=pocket,
            archive=archive)

        return spph

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
                       pub_source=None,
                       version='666',
                       architecturespecific=False,
                       builder=None,
                       component='main'):
        """Return a list of binary publishing records."""
        if distroseries is None:
            distroseries = self.distroseries

        if archive is None:
            archive = distroseries.main_archive

        if pub_source is None:
            sourcename = "%s" % binaryname.split('-')[0]
            if architecturespecific:
                architecturehintlist = 'any'
            else:
                architecturehintlist = 'all'

            pub_source = self.getPubSource(
                sourcename=sourcename, status=status, pocket=pocket,
                archive=archive, distroseries=distroseries,
                version=version, architecturehintlist=architecturehintlist,
                component=component)
        else:
            archive = pub_source.archive

        builds = pub_source.createMissingBuilds()
        published_binaries = []
        for build in builds:
            build.builder = builder
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
        sourcepackagerelease = build.source_package_release
        distroarchseries = build.distro_arch_series
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

        # Adjust the build record in way it looks complete.
        naked_build = removeSecurityProxy(build)
        naked_build.status = BuildStatus.FULLYBUILT
        naked_build.date_finished = datetime.datetime(
            2008, 1, 1, 0, 5, 0, tzinfo=pytz.UTC)
        naked_build.date_started = (
            build.date_finished - datetime.timedelta(minutes=5))
        buildlog_filename = 'buildlog_%s-%s-%s.%s_%s_%s.txt.gz' % (
            build.distribution.name,
            build.distro_series.name,
            build.distro_arch_series.architecturetag,
            build.source_package_release.name,
            build.source_package_release.version,
            build.status.name)
        naked_build.log = self.addMockFile(
            buildlog_filename, filecontent='Built!',
            restricted=build.archive.private)

        return binarypackagerelease

    def publishBinaryInArchive(
        self, binarypackagerelease, archive,
        status=PackagePublishingStatus.PENDING,
        pocket=PackagePublishingPocket.RELEASE,
        scheduleddeletiondate=None, dateremoved=None):
        """Return the corresponding BinaryPackagePublishingHistory."""
        distroarchseries = binarypackagerelease.build.distro_arch_series

        # Publish the binary.
        if binarypackagerelease.architecturespecific:
            archs = [distroarchseries]
        else:
            archs = distroarchseries.distroseries.architectures

        pub_binaries = []
        for arch in archs:
            pub = BinaryPackagePublishingHistory(
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
                archive=archive)
            if status == PackagePublishingStatus.PUBLISHED:
                pub.datepublished = UTC_NOW
            pub_binaries.append(pub)

        return pub_binaries

    def _findChangesFile(self, top, name_fragment):
        """File with given name fragment in directory tree starting at top."""
        for root, dirs, files in os.walk(top, topdown=False):
            for name in files:
                if (name.endswith('.changes') and
                    name.find(name_fragment) > -1):
                    return os.path.join(root, name)
        return None

    def createSource(
        self, archive, sourcename, version, distroseries=None,
        new_version=None):
        """Create source with meaningful '.changes' file."""
        top = 'lib/lp/archiveuploader/tests/data/suite'
        name_fragment = '%s_%s' % (sourcename, version)
        changesfile_path = self._findChangesFile(top, name_fragment)

        source = None

        if changesfile_path is not None:
            if new_version is None:
                new_version = version
            changesfile_content = ''
            handle = open(changesfile_path, 'r')
            try:
                changesfile_content = handle.read()
            finally:
                handle.close()

            source = self.getPubSource(
                sourcename=sourcename, archive=archive, version=new_version,
                changes_file_content=changesfile_content,
                distroseries=distroseries)

        return source


class TestNativePublishingBase(TestCaseWithFactory, SoyuzTestPublisher):
    layer = LaunchpadZopelessLayer
    dbuser = config.archivepublisher.dbuser

    def __init__(self, methodName='runTest'):
        super(TestNativePublishingBase, self).__init__(methodName=methodName)
        SoyuzTestPublisher.__init__(self)

    def setUp(self):
        """Setup a pool dir, the librarian, and instantiate the DiskPool."""
        super(TestNativePublishingBase, self).setUp()
        self.layer.switchDbUser(config.archivepublisher.dbuser)
        self.prepareBreezyAutotest()
        self.config = Config(self.ubuntutest)
        self.config.setupArchiveDirs()
        self.pool_dir = self.config.poolroot
        self.temp_dir = self.config.temproot
        self.logger = FakeLogger()

        self.logger.message = FakeMethod()
        self.disk_pool = DiskPool(self.pool_dir, self.temp_dir, self.logger)

    def tearDown(self):
        """Tear down blows the pool dir away."""
        super(TestNativePublishingBase, self).tearDown()
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

    def checkPublication(self, pub, status):
        """Assert the publication has the given status."""
        self.assertEqual(
            pub.status, status, "%s is not %s (%s)" % (
            pub.displayname, status.name, pub.status.name))

    def checkPublications(self, pubs, status):
        """Assert the given publications have the given status.

        See `checkPublication`.
        """
        for pub in pubs:
            self.checkPublication(pub, status)

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

    def checkSuperseded(self, pubs, supersededby=None):
        self.checkPublications(pubs, PackagePublishingStatus.SUPERSEDED)
        for pub in pubs:
            self.checkPastDate(pub.datesuperseded)
            if supersededby is not None:
                if isinstance(pub, BinaryPackagePublishingHistory):
                    dominant = supersededby.binarypackagerelease.build
                else:
                    dominant = supersededby.sourcepackagerelease
                self.assertEquals(dominant, pub.supersededby)
            else:
                self.assertIs(None, pub.supersededby)


class TestNativePublishing(TestNativePublishingBase):

    def test_publish_source(self):
        # Source publications result in a PUBLISHED publishing record and
        # the corresponding files are dumped in the disk pool/.
        pub_source = self.getPubSource(filecontent='Hello world')
        pub_source.publish(self.disk_pool, self.logger)
        self.assertEqual(
            PackagePublishingStatus.PUBLISHED,
            pub_source.status)
        pool_path = "%s/main/f/foo/foo_666.dsc" % self.pool_dir
        self.assertEqual(open(pool_path).read().strip(), 'Hello world')

    def test_publish_binaries(self):
        # Binary publications result in a PUBLISHED publishing record and
        # the corresponding files are dumped in the disk pool/.
        pub_binary = self.getPubBinaries(filecontent='Hello world')[0]
        pub_binary.publish(self.disk_pool, self.logger)
        self.assertEqual(
            PackagePublishingStatus.PUBLISHED,
            pub_binary.status)
        pool_path = "%s/main/f/foo/foo-bin_666_all.deb" % self.pool_dir
        self.assertEqual(open(pool_path).read().strip(), 'Hello world')

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

        # And an oops should be filed for the error.
        error_utility = ErrorReportingUtility()
        error_report = error_utility.getLastOopsReport()
        fp = StringIO()
        error_report.write(fp)
        error_text = fp.getvalue()
        self.assertTrue("PoolFileOverwriteError" in error_text)

        self.layer.commit()
        self.assertEqual(
            pub_source.status, PackagePublishingStatus.PENDING)
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


class OverrideFromAncestryTestCase(TestCaseWithFactory):
    """Test `IPublishing.overrideFromAncestry`.

    When called from a `SourcePackagePublishingHistory` or a
    `BinaryPackagePublishingHistory` it sets the object target component
    according to its ancestry if available or falls back to the component
    it was originally uploaded to.
    """
    layer = LaunchpadZopelessLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.test_publisher = SoyuzTestPublisher()
        self.test_publisher.prepareBreezyAutotest()

    def test_overrideFromAncestry_only_works_for_pending_records(self):
        # overrideFromAncestry only accepts PENDING publishing records.
        source = self.test_publisher.getPubSource()

        forbidden_status = [
            item
            for item in PackagePublishingStatus.items
            if item is not PackagePublishingStatus.PENDING]

        for status in forbidden_status:
            source.status = status
            self.layer.commit()
            self.assertRaisesWithContent(
                AssertionError,
                'Cannot override published records.',
                source.overrideFromAncestry)

    def makeSource(self):
        """Return a 'source' publication.

        It's pending publication with binaries in a brand new PPA
        and in 'main' component.
        """
        test_archive = self.factory.makeArchive(
            distribution=self.test_publisher.ubuntutest,
            purpose = ArchivePurpose.PPA)
        source = self.test_publisher.getPubSource(archive=test_archive)
        self.test_publisher.getPubBinaries(pub_source=source)
        return source

    def copyAndCheck(self, pub_record, series, component_name):
        """Copy and check if overrideFromAncestry is working as expected.

        The copied publishing record is targeted to the same component
        as its source, but override_from_ancestry changes it to follow
        the ancestry or fallback to the SPR/BPR original component.
        """
        copied = pub_record.copyTo(
            series, pub_record.pocket, series.main_archive)

        # Cope with heterogeneous results from copyTo().
        try:
            copies = tuple(copied)
        except TypeError:
            copies = (copied, )

        for copy in copies:
            self.assertEquals(copy.component, pub_record.component)
            copy.overrideFromAncestry()
            self.layer.commit()
            self.assertEquals(copy.component.name, 'universe')

    def test_overrideFromAncestry_fallback_to_source_component(self):
        # overrideFromancestry on the lack of ancestry, falls back to the
        # component the source was originally uploaded to.
        source = self.makeSource()

        # Adjust the source package release original component.
        universe = getUtility(IComponentSet)['universe']
        source.sourcepackagerelease.component = universe

        self.copyAndCheck(source, source.distroseries, 'universe')

    def test_overrideFromAncestry_fallback_to_binary_component(self):
        # overrideFromAncestry on the lack of ancestry, falls back to the
        # component the binary was originally uploaded to.
        binary = self.makeSource().getPublishedBinaries()[0]

        # Adjust the binary package release original component.
        universe = getUtility(IComponentSet)['universe']
        removeSecurityProxy(binary.binarypackagerelease).component = universe

        self.copyAndCheck(
            binary, binary.distroarchseries.distroseries, 'universe')

    def test_overrideFromAncestry_follow_ancestry_source_component(self):
        # overrideFromAncestry finds and uses the component of the most
        # recent PUBLISHED publication of the same name in the same
        #location.
        source = self.makeSource()

        # Create a published ancestry source in the copy destination
        # targeted to 'universe' and also 2 other noise source
        # publications, a pending source target to 'restricted' and
        # a published, but older, one target to 'multiverse'.
        self.test_publisher.getPubSource(component='restricted')

        self.test_publisher.getPubSource(
            component='multiverse', status=PackagePublishingStatus.PUBLISHED)

        self.test_publisher.getPubSource(
            component='universe', status=PackagePublishingStatus.PUBLISHED)

        # Overridden copy it targeted to 'universe'.
        self.copyAndCheck(source, source.distroseries, 'universe')

    def test_overrideFromAncestry_follow_ancestry_binary_component(self):
        # overrideFromAncestry finds and uses the component of the most
        # recent published publication of the same name in the same
        # location.
        binary = self.makeSource().getPublishedBinaries()[0]

        # Create a published ancestry binary in the copy destination
        # targeted to 'universe'.
        restricted_source = self.test_publisher.getPubSource(
            component='restricted')
        self.test_publisher.getPubBinaries(pub_source=restricted_source)

        multiverse_source = self.test_publisher.getPubSource(
            component='multiverse')
        self.test_publisher.getPubBinaries(
            pub_source=multiverse_source,
            status=PackagePublishingStatus.PUBLISHED)

        ancestry_source = self.test_publisher.getPubSource(
            component='universe')
        self.test_publisher.getPubBinaries(
            pub_source=ancestry_source,
            status=PackagePublishingStatus.PUBLISHED)

        # Overridden copy it targeted to 'universe'.
        self.copyAndCheck(
            binary, binary.distroarchseries.distroseries, 'universe')


class BuildRecordCreationTests(TestNativePublishingBase):
    """Test the creation of build records."""

    def setUp(self):
        super(BuildRecordCreationTests, self).setUp()
        self.distro = self.factory.makeDistribution()
        self.distroseries = self.factory.makeDistroSeries(
            distribution=self.distro, name="crazy")
        self.archive = self.factory.makeArchive()
        self.avr_family = self.factory.makeProcessorFamily(
            name="avr", restricted=True)
        self.factory.makeProcessor(self.avr_family, "avr2001")
        self.avr_distroarch = self.factory.makeDistroArchSeries(
            architecturetag='avr', processorfamily=self.avr_family,
            distroseries=self.distroseries, supports_virtualized=True)
        self.sparc_family = self.factory.makeProcessorFamily(name="sparc",
            restricted=False)
        self.factory.makeProcessor(self.sparc_family, "sparc64")
        self.sparc_distroarch = self.factory.makeDistroArchSeries(
            architecturetag='sparc', processorfamily=self.sparc_family,
            distroseries=self.distroseries, supports_virtualized=True)
        self.distroseries.nominatedarchindep = self.sparc_distroarch
        self.addFakeChroots(self.distroseries)

    def getPubSource(self, architecturehintlist):
        """Return a mock source package publishing record for the archive
        and architecture used in this testcase.

        :param architecturehintlist: Architecture hint list
            (e.g. "i386 amd64")
        """
        return super(BuildRecordCreationTests, self).getPubSource(
            archive=self.archive, distroseries=self.distroseries,
            architecturehintlist=architecturehintlist)

    def test__getAllowedArchitectures_restricted(self):
        """Test _getAllowedArchitectures doesn't return unrestricted
        archs.

        For a normal archive, only unrestricted architectures should
        be used.
        """
        available_archs = [self.sparc_distroarch, self.avr_distroarch]
        pubrec = self.getPubSource(architecturehintlist='any')
        self.assertEquals([self.sparc_distroarch],
            pubrec._getAllowedArchitectures(available_archs))

    def test__getAllowedArchitectures_restricted_override(self):
        """Test _getAllowedArchitectures honors overrides of restricted archs.

        Restricted architectures should only be allowed if there is
        an explicit ArchiveArch association with the archive.
        """
        available_archs = [self.sparc_distroarch, self.avr_distroarch]
        getUtility(IArchiveArchSet).new(self.archive, self.avr_family)
        pubrec = self.getPubSource(architecturehintlist='any')
        self.assertEquals([self.sparc_distroarch, self.avr_distroarch],
            pubrec._getAllowedArchitectures(available_archs))

    def test_createMissingBuilds_restricts_any(self):
        """createMissingBuilds() should limit builds targeted at 'any'
        architecture to those allowed for the archive.
        """
        pubrec = self.getPubSource(architecturehintlist='any')
        builds = pubrec.createMissingBuilds()
        self.assertEquals(1, len(builds))
        self.assertEquals(self.sparc_distroarch, builds[0].distro_arch_series)

    def test_createMissingBuilds_restricts_explicitlist(self):
        """createMissingBuilds() limits builds targeted at a variety of
        architectures architecture to those allowed for the archive.
        """
        pubrec = self.getPubSource(architecturehintlist='sparc i386 avr')
        builds = pubrec.createMissingBuilds()
        self.assertEquals(1, len(builds))
        self.assertEquals(self.sparc_distroarch, builds[0].distro_arch_series)

    def test_createMissingBuilds_restricts_all(self):
        """createMissingBuilds() should limit builds targeted at 'all'
        architectures to the nominated independent architecture,
        if that is allowed for the archive.
        """
        pubrec = self.getPubSource(architecturehintlist='all')
        builds = pubrec.createMissingBuilds()
        self.assertEquals(1, len(builds))
        self.assertEquals(self.sparc_distroarch, builds[0].distro_arch_series)

    def test_createMissingBuilds_restrict_override(self):
        """createMissingBuilds() should limit builds targeted at 'any'
        architecture to architectures that are unrestricted or
        explicitly associated with the archive.
        """
        getUtility(IArchiveArchSet).new(self.archive, self.avr_family)
        pubrec = self.getPubSource(architecturehintlist='any')
        builds = pubrec.createMissingBuilds()
        self.assertEquals(2, len(builds))
        self.assertEquals(self.avr_distroarch, builds[0].distro_arch_series)
        self.assertEquals(self.sparc_distroarch, builds[1].distro_arch_series)


class PublishingSetTests(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(PublishingSetTests, self).setUp()
        self.distroseries = self.factory.makeDistroSeries()
        self.archive = self.factory.makeArchive(
            distribution=self.distroseries.distribution)
        self.publishing = self.factory.makeSourcePackagePublishingHistory(
            distroseries=self.distroseries, archive=self.archive)
        self.publishing_set = getUtility(IPublishingSet)

    def test_getByIdAndArchive_finds_record(self):
        record = self.publishing_set.getByIdAndArchive(
            self.publishing.id, self.archive)
        self.assertEqual(self.publishing, record)

    def test_getByIdAndArchive_finds_record_explicit_source(self):
        record = self.publishing_set.getByIdAndArchive(
            self.publishing.id, self.archive, source=True)
        self.assertEqual(self.publishing, record)

    def test_getByIdAndArchive_wrong_archive(self):
        wrong_archive = self.factory.makeArchive()
        record = self.publishing_set.getByIdAndArchive(
            self.publishing.id, wrong_archive)
        self.assertEqual(None, record)

    def makeBinaryPublishing(self):
        distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=self.distroseries)
        binary_publishing = self.factory.makeBinaryPackagePublishingHistory(
            archive=self.archive, distroarchseries=distroarchseries)
        return binary_publishing

    def test_getByIdAndArchive_wrong_type(self):
        self.makeBinaryPublishing()
        record = self.publishing_set.getByIdAndArchive(
            self.publishing.id, self.archive, source=False)
        self.assertEqual(None, record)

    def test_getByIdAndArchive_finds_binary(self):
        binary_publishing = self.makeBinaryPublishing()
        record = self.publishing_set.getByIdAndArchive(
            binary_publishing.id, self.archive, source=False)
        self.assertEqual(binary_publishing, record)

    def test_getByIdAndArchive_binary_wrong_archive(self):
        binary_publishing = self.makeBinaryPublishing()
        wrong_archive = self.factory.makeArchive()
        record = self.publishing_set.getByIdAndArchive(
            binary_publishing.id, wrong_archive, source=False)
        self.assertEqual(None, record)


class TestSourceDomination(TestNativePublishingBase):
    """Test SourcePackagePublishingHistory.supersede() operates correctly."""

    def testSupersede(self):
        """Check that supersede() without arguments works."""
        source = self.getPubSource()
        source.supersede()
        self.checkSuperseded([source])

    def testSupersedeWithDominant(self):
        """Check that supersede() with a dominant publication works."""
        source = self.getPubSource()
        super_source = self.getPubSource()
        source.supersede(super_source)
        self.checkSuperseded([source], super_source)

    def testSupersedingSupersededSourceFails(self):
        """Check that supersede() fails with a superseded source.

        Sources should not be superseded twice. If a second attempt is made,
        the Dominator's lookups are buggy.
        """
        source = self.getPubSource()
        super_source = self.getPubSource()
        source.supersede(super_source)
        self.checkSuperseded([source], super_source)

        # Manually set a date in the past, so we can confirm that
        # the second supersede() fails properly.
        source.datesuperseded = datetime.datetime(
            2006, 12, 25, tzinfo=pytz.timezone("UTC"))
        super_date = source.datesuperseded

        self.assertRaises(AssertionError, source.supersede, super_source)
        self.checkSuperseded([source], super_source)
        self.assertEquals(super_date, source.datesuperseded)


class TestBinaryDomination(TestNativePublishingBase):
    """Test BinaryPackagePublishingHistory.supersede() operates correctly."""

    def testSupersede(self):
        """Check that supersede() without arguments works."""
        bins = self.getPubBinaries(architecturespecific=True)
        bins[0].supersede()
        self.checkSuperseded([bins[0]])
        self.checkPublication(bins[1], PackagePublishingStatus.PENDING)

    def testSupersedeWithDominant(self):
        """Check that supersede() with a dominant publication works."""
        bins = self.getPubBinaries(architecturespecific=True)
        super_bins = self.getPubBinaries(architecturespecific=True)
        bins[0].supersede(super_bins[0])
        self.checkSuperseded([bins[0]], super_bins[0])
        self.checkPublication(bins[1], PackagePublishingStatus.PENDING)

    def testSupersedesArchIndepBinariesAtomically(self):
        """Check that supersede() supersedes arch-indep binaries atomically.

        Architecture-independent binaries should be removed from all
        architectures when they are superseded on at least one (bug #48760).
        """
        bins = self.getPubBinaries(architecturespecific=False)
        super_bins = self.getPubBinaries(architecturespecific=False)
        bins[0].supersede(super_bins[0])
        self.checkSuperseded(bins, super_bins[0])

    def testAtomicDominationRespectsOverrides(self):
        """Check that atomic domination only covers identical overrides.

        This is important, as otherwise newly-overridden arch-indep binaries
        will supersede themselves, and vanish entirely (bug #178102).
        """
        bins = self.getPubBinaries(architecturespecific=False)

        universe = getUtility(IComponentSet)['universe']
        super_bins = []
        for bin in bins:
            super_bins.append(bin.changeOverride(new_component=universe))

        bins[0].supersede(super_bins[0])
        self.checkSuperseded(bins, super_bins[0])
        self.checkPublications(super_bins, PackagePublishingStatus.PENDING)

    def testSupersedingSupersededArchSpecificBinaryFails(self):
        """Check that supersede() fails with a superseded arch-dep binary.

        Architecture-specific binaries should not normally be superseded
        twice. If a second attempt is made, the Dominator's lookups are buggy.
        """
        bin = self.getPubBinaries(architecturespecific=True)[0]
        super_bin = self.getPubBinaries(architecturespecific=True)[0]
        bin.supersede(super_bin)

        # Manually set a date in the past, so we can confirm that
        # the second supersede() fails properly.
        bin.datesuperseded = datetime.datetime(
            2006, 12, 25, tzinfo=pytz.timezone("UTC"))
        super_date = bin.datesuperseded

        self.assertRaises(AssertionError, bin.supersede, super_bin)
        self.checkSuperseded([bin], super_bin)
        self.assertEquals(super_date, bin.datesuperseded)

    def testSkipsSupersededArchIndependentBinary(self):
        """Check that supersede() skips a superseded arch-indep binary.

        Since all publications of an architecture-independent binary are
        superseded atomically, they may be superseded again later. In that
        case, we skip the domination, leaving the old date unchanged.
        """
        bin = self.getPubBinaries(architecturespecific=False)[0]
        super_bin = self.getPubBinaries(architecturespecific=False)[0]
        bin.supersede(super_bin)
        self.checkSuperseded([bin], super_bin)

        # Manually set a date in the past, so we can confirm that
        # the second supersede() skips properly.
        bin.datesuperseded = datetime.datetime(
            2006, 12, 25, tzinfo=pytz.timezone("UTC"))
        super_date = bin.datesuperseded

        bin.supersede(super_bin)
        self.checkSuperseded([bin], super_bin)
        self.assertEquals(super_date, bin.datesuperseded)


class TestBinaryGetOtherPublications(TestNativePublishingBase):
    """Test BinaryPackagePublishingHistory._getOtherPublications() works."""

    def checkOtherPublications(self, this, others):
        self.assertEquals(
            set(removeSecurityProxy(this)._getOtherPublications()),
            set(others))

    def testFindsOtherArchIndepPublications(self):
        """Arch-indep publications with the same overrides should be found."""
        bins = self.getPubBinaries(architecturespecific=False)
        self.checkOtherPublications(bins[0], bins)

    def testDoesntFindArchSpecificPublications(self):
        """Arch-dep publications shouldn't be found."""
        bins = self.getPubBinaries(architecturespecific=True)
        self.checkOtherPublications(bins[0], [bins[0]])

    def testDoesntFindPublicationsInOtherArchives(self):
        """Publications in other archives shouldn't be found."""
        bins = self.getPubBinaries(architecturespecific=False)
        foreign_bins = bins[0].copyTo(
            bins[0].distroarchseries.distroseries, bins[0].pocket,
            self.factory.makeArchive())
        self.checkOtherPublications(bins[0], bins)
        self.checkOtherPublications(foreign_bins[0], foreign_bins)

    def testDoesntFindPublicationsWithDifferentOverrides(self):
        """Publications with different overrides shouldn't be found."""
        bins = self.getPubBinaries(architecturespecific=False)
        universe = getUtility(IComponentSet)['universe']
        foreign_bin = bins[0].changeOverride(new_component=universe)
        self.checkOtherPublications(bins[0], bins)
        self.checkOtherPublications(foreign_bin, [foreign_bin])

    def testDoesntFindSupersededPublications(self):
        """Superseded publications shouldn't be found."""
        bins = self.getPubBinaries(architecturespecific=False)
        self.checkOtherPublications(bins[0], bins)
        # This will supersede both atomically.
        bins[0].supersede()
        self.checkOtherPublications(bins[0], [])
