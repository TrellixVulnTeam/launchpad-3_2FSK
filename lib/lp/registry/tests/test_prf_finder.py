# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import logging
import os
import shutil
import tempfile
import unittest
from StringIO import StringIO

from zope.component import getUtility
from zope.interface.verify import verifyObject
from zope.schema import getFields

from canonical.config import config
from canonical.testing import LaunchpadZopelessLayer, reset_logging

from lp.registry.interfaces.product import IProductSet
from lp.registry.interfaces.productrelease import (
    IProductReleaseFile, UpstreamFileType)
from lp.registry.scripts.productreleasefinder.filter import (
    FilterPattern)
from lp.registry.scripts.productreleasefinder.finder import (
    extract_version, ProductReleaseFinder)


class FindReleasesTestCase(unittest.TestCase):

    def test_findReleases(self):
        # test that the findReleases() method behaves as expected

        class DummyProductReleaseFinder(ProductReleaseFinder):

            def __init__(self):
                ProductReleaseFinder.__init__(self, None, None)
                self.seen_products = []

            def getFilters(self):
                return [('product1', ['filter1', 'filter2']),
                        ('product2', ['filter3', 'filter4'])]

            def handleProduct(self, product_name, filters):
                self.seen_products.append((product_name, filters))

        prf = DummyProductReleaseFinder()
        prf.findReleases()
        self.assertEqual(len(prf.seen_products), 2)
        self.assertEqual(prf.seen_products[0],
                         ('product1', ['filter1', 'filter2']))
        self.assertEqual(prf.seen_products[1],
                         ('product2', ['filter3', 'filter4']))


class GetFiltersTestCase(unittest.TestCase):

    layer = LaunchpadZopelessLayer

    def test_getFilters(self):
        # test that getFilters() correctly extracts file patterns from
        # the database.

        ztm = self.layer.txn
        ztm.begin()

        evolution = getUtility(IProductSet).getByName('evolution')
        trunk = evolution.getSeries('trunk')
        trunk.releasefileglob = ('http://ftp.gnome.org/pub/GNOME/sources/'
                                 'evolution/2.7/evolution-*.tar.gz')
        ztm.commit()

        logging.basicConfig(level=logging.CRITICAL)
        prf = ProductReleaseFinder(ztm, logging.getLogger())
        # get the filters for evolution and firefox
        for product_name, filters in prf.getFilters():
            if product_name == 'evolution':
                evo_filters = filters

        self.assertEqual(len(evo_filters), 1)
        self.failUnless(isinstance(evo_filters[0], FilterPattern))
        self.assertEqual(evo_filters[0].key, 'trunk')
        self.assertEqual(evo_filters[0].base_url,
            'http://ftp.gnome.org/pub/GNOME/sources/evolution/2.7/')
        self.assertEqual(evo_filters[0].urlglob,
            'http://ftp.gnome.org/pub/GNOME/sources/evolution/2.7/'
            'evolution-*.tar.gz')
        self.failUnless(evo_filters[0].match(
            'http://ftp.gnome.org/pub/GNOME/sources/evolution/2.7/'
            'evolution-2.7.1.tar.gz'))


class HandleProductTestCase(unittest.TestCase):

    def setUp(self):
        # path for release tree
        self.release_root = tempfile.mkdtemp()
        self.release_url = 'file://' + self.release_root

    def tearDown(self):
        shutil.rmtree(self.release_root, ignore_errors=True)
        reset_logging()

    def test_handleProduct(self):
        # test that handleProduct() correctly calls handleRelease()
        class DummyProductReleaseFinder(ProductReleaseFinder):
            def __init__(self, ztm, log):
                ProductReleaseFinder.__init__(self, ztm, log)
                self.seen_releases = []

            def handleRelease(self, product_name, series_name, url):
                self.seen_releases.append((product_name, series_name,
                                           os.path.basename(url)))

        # create releases tree
        os.mkdir(os.path.join(self.release_root, 'product'))
        for series in ['1', '2']:
            os.mkdir(os.path.join(self.release_root, 'product', series))
            # something that isn't a release
            fp = open(os.path.join(self.release_root, 'product', series,
                                   'not-a-release.tar.gz'), 'w')
            fp.write('not-a-release')
            fp.close()
            # write two releases per series
            for release in ['0', '1']:
                fp = open(os.path.join(self.release_root, 'product', series,
                          'product-%s.%s.tar.gz' % (series, release)), 'w')
                fp.write('foo')
                fp.close()

        logging.basicConfig(level=logging.CRITICAL)
        prf = DummyProductReleaseFinder(None, logging.getLogger())

        filters = [
            FilterPattern('series1', self.release_url +
                          '/product/1/product-1.*.tar.gz'),
            FilterPattern('series2', self.release_url +
                          '/product/2/product-2.*.tar.gz'),
            ]


        prf.handleProduct('product', filters)
        prf.seen_releases.sort()
        self.assertEqual(len(prf.seen_releases), 4)
        self.assertEqual(prf.seen_releases[0],
                         ('product', 'series1', 'product-1.0.tar.gz'))
        self.assertEqual(prf.seen_releases[1],
                         ('product', 'series1', 'product-1.1.tar.gz'))
        self.assertEqual(prf.seen_releases[2],
                         ('product', 'series2', 'product-2.0.tar.gz'))
        self.assertEqual(prf.seen_releases[3],
                         ('product', 'series2', 'product-2.1.tar.gz'))


class HandleReleaseTestCase(unittest.TestCase):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        LaunchpadZopelessLayer.switchDbUser(
            config.productreleasefinder.dbuser)
        self.release_root = tempfile.mkdtemp()
        self.release_url = 'file://' + self.release_root

    def tearDown(self):
        shutil.rmtree(self.release_root, ignore_errors=True)
        reset_logging()

    def test_handleRelease(self):
        ztm = self.layer.txn
        logging.basicConfig(level=logging.CRITICAL)
        prf = ProductReleaseFinder(ztm, logging.getLogger())
        file_name = 'evolution-42.0.orig.tar.gz'
        alt_file_name = 'evolution-42.0.orig.tar.bz2'

        # create a release tarball
        fp = open(os.path.join(
            self.release_root, file_name), 'w')
        fp.write('foo')
        fp.close()

        self.assertEqual(
            prf.hasReleaseFile('evolution', 'trunk', '42.0', file_name),
            False)
        self.assertEqual(
            prf.hasReleaseFile('evolution', 'trunk', '42.0', alt_file_name),
            False)

        prf.handleRelease(
            'evolution', 'trunk', self.release_url + '/' + file_name)

        self.assertEqual(
            prf.hasReleaseFile('evolution', 'trunk', '42.0', file_name),
            True)
        self.assertEqual(
            prf.hasReleaseFile('evolution', 'trunk', '42.0', alt_file_name),
            False)

        # check to see that the release has been created
        evo = getUtility(IProductSet).getByName('evolution')
        trunk = evo.getSeries('trunk')
        release = trunk.getRelease('42.0')
        self.assertNotEqual(release, None)
        self.assertEqual(release.files.count(), 1)
        fileinfo = release.files[0]
        self.assertEqual(fileinfo.filetype, UpstreamFileType.CODETARBALL)
        self.assertEqual(fileinfo.libraryfile.filename, file_name)

        # verify that the fileinfo object is sane
        self.failUnless(verifyObject(IProductReleaseFile, fileinfo))
        for field in getFields(IProductReleaseFile).values():
            # XXX: BradCrittenden 2008-09-04 bug=264829:
            # Several interfaces have uploaded files as `Bytes` attributes but
            # then the values get converted to LibraryFileAlias objects.  The
            # Bytes._validate() method then fails.  As a work-around the
            # validate test is being disabled here for those fields.
            from zope.schema import Bytes
            if isinstance(field, Bytes):
                continue
            bound = field.bind(fileinfo)
            bound.validate(bound.get(fileinfo))

    def test_handleReleaseWithExistingRelease(self):
        # Test that handleRelease() can add a file release to an
        # existing ProductRelease.
        ztm = self.layer.txn

        # verify that a 2.1.6 release of evolution exists without any
        # files attached.
        evo = getUtility(IProductSet).getByName('evolution')
        trunk = evo.getSeries('trunk')
        release = trunk.getRelease('2.1.6')
        self.assertNotEqual(release, None)
        self.assertEqual(release.files.count(), 0)
        ztm.abort()

        logging.basicConfig(level=logging.CRITICAL)
        prf = ProductReleaseFinder(ztm, logging.getLogger())

        # create a release tarball
        fp = open(os.path.join(
            self.release_root, 'evolution-2.1.6.tar.gz'), 'w')
        fp.write('foo')
        fp.close()

        prf.handleRelease('evolution', 'trunk',
                          self.release_url + '/evolution-2.1.6.tar.gz')

        # verify that we now have files attached to the release:
        evo = getUtility(IProductSet).getByName('evolution')
        trunk = evo.getSeries('trunk')
        release = trunk.getRelease('2.1.6')
        self.assertEqual(release.files.count(), 1)

    def test_handleReleaseTwice(self):
        # Test that handleRelease() handles the case where a tarball
        # has already been attached to the ProductRelease.  We do this
        # by calling handleRelease() twice.
        ztm = self.layer.txn
        logging.basicConfig(level=logging.CRITICAL)
        prf = ProductReleaseFinder(ztm, logging.getLogger())

        # create a release tarball
        fp = open(os.path.join(
            self.release_root, 'evolution-42.0.tar.gz'), 'w')
        fp.write('foo')
        fp.close()

        prf.handleRelease('evolution', 'trunk',
                          self.release_url + '/evolution-42.0.tar.gz')
        prf.handleRelease('evolution', 'trunk',
                          self.release_url + '/evolution-42.0.tar.gz')

        evo = getUtility(IProductSet).getByName('evolution')
        trunk = evo.getSeries('trunk')
        release = trunk.getRelease('42.0')
        self.assertEqual(release.files.count(), 1)

    def test_handleReleaseUnableToParseVersion(self):
        # Test that handleRelease() handles the case where a version can't be
        # parsed from the url given.
        ztm = self.layer.txn
        output = StringIO()
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(logging.StreamHandler(output))
        prf = ProductReleaseFinder(ztm, logger)

        # create a release tarball
        fp = open(os.path.join(
            self.release_root, 'evolution-42.0.tar.gz'), 'w')
        fp.write('foo')
        fp.close()

        url = self.release_url + '/evolution420.tar.gz'
        prf.handleRelease('evolution', 'trunk', url)
        self.assertEqual(
            "Unable to parse version from %s\n" % url, output.getvalue())


class ExtractVersionTestCase(unittest.TestCase):
    """Verify that release version names are correctly extracted."""

    def test_extract_version_common_name(self):
        """Verify the common file names."""
        version = extract_version('emacs-21.10.tar.gz')
        self.assertEqual(version, '21.10')
        version = extract_version('emacs-21.10.01.tar.gz')
        self.assertEqual(version, '21.10.01')
        version = extract_version('emacs-21.10.01.2.tar.gz')
        self.assertEqual(version, '21.10.01.2')
        version = extract_version('bzr-1.15rc1.tar.gz')
        self.assertEqual(version, '1.15rc1')
        version = extract_version('bzr-1.15_rc1.tar.gz')
        self.assertEqual(version, '1.15-rc1')
        version = extract_version('bzr-1.15_beta1.tar.gz')
        self.assertEqual(version, '1.15-beta1')

    def test_extract_version_debian_name(self):
        """Verify that the debian-style .orig suffix is handled."""
        version = extract_version('emacs-21.10.orig.tar.gz')
        self.assertEqual(version, '21.10')

    def test_extract_version_name_with_supported_types(self):
        """Verify that the file's mimetype is supported."""
        version = extract_version('emacs-21.10.tar.gz')
        self.assertEqual(version, '21.10')
        version = extract_version('emacs-21.10.tar')
        self.assertEqual(version, '21.10')
        version = extract_version('emacs-21.10.gz')
        self.assertEqual(version, '21.10')
        version = extract_version('emacs-21.10.tar.Z')
        self.assertEqual(version, '21.10')
        version = extract_version('emacs-21.10.tar.bz2')
        self.assertEqual(version, '21.10')
        version = extract_version('emacs-21.10.zip')
        self.assertEqual(version, '21.10')

    def test_extract_version_name_with_flavors(self):
        """Verify that language, processor, and packaging are removed."""
        version = extract_version('furiusisomount-0.8.1.0_de_DE.tar.gz')
        self.assertEqual(version, '0.8.1.0')
        version = extract_version('glow-0.2.0_all.deb')
        self.assertEqual(version, '0.2.0')
        version = extract_version('glow-0.2.1_i386.deb')
        self.assertEqual(version, '0.2.1')
        version = extract_version('ipython-0.8.4.win32-setup.exe')
        self.assertEqual(version, '0.8.4')
        version = extract_version('Bazaar-1.16.1.win32-py2.5.exe')
        self.assertEqual(version, '1.16.1')
        version = extract_version(' Bazaar-1.16.0-OSX10.5.dmg')
        self.assertEqual(version, '1.16.0')
        version = extract_version('Bazaar-1.16.2-OSX10.4-universal-py25.dmg')
        self.assertEqual(version, '1.16.2')
        version = extract_version('Bazaar-1.16.3.exe')
        self.assertEqual(version, '1.16.3')
        version = extract_version('partitionmanager-21-2.noarch.rpm')
        self.assertEqual(version, '21-2')
        version = extract_version('php-fpm-0.6~5.3.1.tar.gz')
        self.assertEqual(version, '0.6')

    def test_extract_version_name_with_uppercase(self):
        """Verify that the file's version is lowercases."""
        version = extract_version('client-2.4p1A.tar.gz')
        self.assertEqual(version, '2.4p1a')

    def test_extract_version_name_with_bad_characters(self):
        """Verify that the file's version is lowercases."""
        version = extract_version('vpnc-0.2-rm+zomb-pre1.tar.gz')
        self.assertEqual(version, '0.2-rm-zomb-pre1')
        version = extract_version('warzone2100-2.0.5_rc1.tar.bz2')
        self.assertEqual(version, '2.0.5-rc1')


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
