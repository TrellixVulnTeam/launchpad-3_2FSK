# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

import logging
import os
import shutil
import tempfile
import unittest

from zope.component import getUtility

from canonical.config import config
from canonical.testing import LaunchpadZopelessLayer, reset_logging
from canonical.launchpad.interfaces import IProductSet
from canonical.lp.dbschema import UpstreamFileType
from canonical.launchpad.scripts.productreleasefinder.filter import (
    FilterPattern)
from canonical.launchpad.scripts.productreleasefinder.finder import (
    ProductReleaseFinder)


class FindReleasesTestCase(unittest.TestCase):

    def test_findReleases(self):
        # test that the findReleases() method behaves as expected

        class DummyProductReleaseFinder(ProductReleaseFinder):

            def __init__(self):
                ProductReleaseFinder.__init__(self, None, None)
                self.cache.save = self.saveCache
                self.seen_products = []

            cache_save_called = False

            def saveCache(self):
                self.cache_save_called = True

            def getFilters(self):
                return [('product1', ['filter1', 'filter2']),
                        ('product2', ['filter3', 'filter4'])]

            def handleProduct(self, product_name, filters):
                self.seen_products.append((product_name, filters))

            # fake cache element
            class cache:
                save_called = False
                @classmethod
                def save(cls):
                    cls.save_called = True

        prf = DummyProductReleaseFinder()
        prf.findReleases()
        self.assertEqual(len(prf.seen_products), 2)
        self.assertEqual(prf.seen_products[0],
                         ('product1', ['filter1', 'filter2']))
        self.assertEqual(prf.seen_products[1],
                         ('product2', ['filter3', 'filter4']))
        self.assertEqual(prf.cache_save_called, True)


class GetFiltersTestCase(unittest.TestCase):

    layer = LaunchpadZopelessLayer

    def test_getFilters(self):
        # test that getFilters() correctly extracts file patterns from
        # the database.
        
        ztm = self.layer.txn
        ztm.begin()

        evolution = getUtility(IProductSet).getByName('evolution')
        trunk = evolution.getSeries('trunk')
        trunk.releaseroot = ('http://ftp.gnome.org/pub/GNOME/sources/'
                             'evolution/2.7/')
        trunk.releasefileglob = 'evolution-*.tar.gz'

        # a product without a release root set for the series
        firefox = getUtility(IProductSet).getByName('firefox')
        firefox.releaseroot = ('http://releases.mozilla.org/pub/'
                               'mozilla.org/firefox/releases/')
        onezero = firefox.getSeries('1.0')
        onezero.releaseroot = None
        onezero.releasefileglob = '1.0*/source/firefox-1.0*-source.tar.bz2'

        ztm.commit()

        logging.basicConfig(level=logging.CRITICAL)
        prf = ProductReleaseFinder(ztm, logging.getLogger())
        # get the filters for evolution and firefox
        for product_name, filters in prf.getFilters():
            if product_name == 'firefox':
                firefox_filters = filters
            elif product_name == 'evolution':
                evo_filters = filters

        self.assertEqual(len(firefox_filters), 1)
        self.failUnless(isinstance(firefox_filters[0], FilterPattern))
        self.assertEqual(firefox_filters[0].key, '1.0')
        self.assertEqual(firefox_filters[0].base_url,
            'http://releases.mozilla.org/pub/mozilla.org/firefox/releases/')
        self.assertEqual(firefox_filters[0].glob,
            '1.0*/source/firefox-1.0*-source.tar.bz2')
        self.failUnless(firefox_filters[0].match(
            'http://releases.mozilla.org/pub/mozilla.org/firefox/releases/'
            '1.0.8/source/firefox-1.0.8-source.tar.bz2'))

        self.assertEqual(len(evo_filters), 1)
        self.failUnless(isinstance(evo_filters[0], FilterPattern))
        self.assertEqual(evo_filters[0].key, 'trunk')
        self.assertEqual(evo_filters[0].base_url,
            'http://ftp.gnome.org/pub/GNOME/sources/evolution/2.7/')
        self.assertEqual(evo_filters[0].glob, 'evolution-*.tar.gz')
        self.failUnless(evo_filters[0].match(
            'http://ftp.gnome.org/pub/GNOME/sources/evolution/2.7/'
            'evolution-2.7.1.tar.gz'))


class HandleProductTestCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()

        # fake cache path
        self._old_cache_path = config.productreleasefinder.cache_path
        cache_path = os.path.join(self.root, 'cache')
        os.mkdir(cache_path)
        config.productreleasefinder.cache_path = cache_path

        # path for release tree
        self.release_root = os.path.join(self.root, 'releases')
        self.release_url = 'file://' + self.release_root
        os.mkdir(self.release_root)

    def tearDown(self):
        config.productreleasefinder.cache_path = self._old_cache_path
        shutil.rmtree(self.root, ignore_errors=True)
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
            FilterPattern('series1', self.release_url + '/product/1',
                          'product-1.*.tar.gz'),
            FilterPattern('series2', self.release_url + '/product/2',
                          'product-2.*.tar.gz'),
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
        self.release_root = tempfile.mkdtemp()
        self.release_url = 'file://' + self.release_root

    def tearDown(self):
        shutil.rmtree(self.release_root, ignore_errors=True)
        reset_logging()

    def test_handleRelease(self):
        ztm = self.layer.txn
        logging.basicConfig(level=logging.CRITICAL)
        prf = ProductReleaseFinder(ztm, logging.getLogger())

        # create a release tarball
        fp = open(os.path.join(
            self.release_root, 'evolution-42.0.tar.gz'), 'w')
        fp.write('foo')
        fp.close()

        self.assertEqual(prf.hasReleaseTarball('evolution', 'trunk', '42.0'),
                         False)

        prf.handleRelease('evolution', 'trunk',
                          self.release_url + '/evolution-42.0.tar.gz')

        self.assertEqual(prf.hasReleaseTarball('evolution', 'trunk', '42.0'),
                         True)

        # check to see that the release has been created
        evo = getUtility(IProductSet).getByName('evolution')
        trunk = evo.getSeries('trunk')
        release = trunk.getRelease('42.0')
        self.assertNotEqual(release, None)
        self.assertEqual(release.files.count(), 1)
        fileinfo = release.files[0]
        self.assertEqual(fileinfo.filetype, UpstreamFileType.CODETARBALL)
        self.assertEqual(fileinfo.libraryfile.filename,
                         'evolution-42.0.tar.gz')

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


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
