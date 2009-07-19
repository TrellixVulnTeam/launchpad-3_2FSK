# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for librarian wrapper (lp.archivepublisher.library.py)"""

__metaclass__ = type

import os
import shutil
import sha
import sys
import unittest

from lp.archivepublisher.tests import datadir

from lp.archivepublisher.tests.util import (
    FakeDownloadClient, FakeUploadClient)


class TestLibrarianWrapper(unittest.TestCase):

    def setUp(self):
        ## Create archive and cache dir ...
        os.mkdir(datadir('archive'))
        os.mkdir(datadir('cache'))

    def tearDown(self):
        shutil.rmtree(datadir('archive'))
        shutil.rmtree(datadir('cache'))

    def testImport(self):
        """Librarian should be importable"""
        from lp.archivepublisher.library import Librarian

    def testInstatiate(self):
        """Librarian should be instantiatable"""
        from lp.archivepublisher.library import Librarian
        lib = Librarian('localhost', 9090, 8000, datadir('cache'))

    def testUpload(self):
        """Librarian Upload"""
        name = 'ed_0.2-20.dsc'
        path = datadir(name)

        from lp.archivepublisher.library import Librarian
        lib = Librarian('localhost', 9090, 8000, datadir('cache'))

        fileobj = open(path, 'rb')
        size = os.stat(path).st_size
        digest = sha.sha(open(path, 'rb').read()).hexdigest()

        ## Use Fake Librarian class
        uploader = FakeUploadClient()

        fileid, filealias = lib.addFile(name, size, fileobj,
                                        contentType='test/test',
                                        digest=digest,
                                        uploader=uploader)
        #print 'ID %s ALIAS %s' %(fileid, filealias)

        cached = os.path.join(datadir('cache'), name)
        os.path.exists(cached)

    def testDownload(self):
        """Librarian DownloadToDisk process"""
        filealias = '1'
        archive = os.path.join (datadir('archive'), 'test')

        from lp.archivepublisher.library import Librarian
        lib = Librarian('localhost', 9090, 8000, datadir('cache'))
        ## Use Fake Librarian Class
        downloader = FakeDownloadClient()

        lib.downloadFileToDisk(filealias, archive, downloader=downloader)

        os.path.exists(archive)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
