# Copyright 2008 Canonical Ltd.  All rights reserved.
"""`MozillaZipFile` tests."""

__metaclass__ = type

import unittest

from canonical.launchpad.translationformat.mozilla_zip import (
    get_file_suffix, MozillaZipFile)
from canonical.launchpad.translationformat.tests.xpi_helpers import (
    get_en_US_xpi_file_to_import)
from canonical.testing import LaunchpadZopelessLayer


class TraversalRecorder(MozillaZipFile):
    """XPI "parser": records traversal of an XPI or jar file.

    Does nothing but keep track of the structure of nested zip files it
    traverses, and the various parameters for each translatable file.

    Produces a nice list of tuples (representing parameters for a
    translatable file) and lists (representing nested jar files).  Each
    zip file's traversal, including nested ones, is concluded with a
    string containing a full stop (".").
    """
    traversal = None

    def _begin(self):
        self.traversal = []

    def _processTranslatableFile(self, entry, locale_code, xpi_path,
                                 chrome_path):
        record = (entry, locale_code, xpi_path, chrome_path)
        self.traversal.append(record)

    def _processNestedJar(self, nested_recorder):
        self.traversal.append(nested_recorder.traversal)

    def _complete(self):
        self.traversal.append('.')


class MozillaZipFileTestCase(unittest.TestCase):
    """Test Mozilla XPI/jar traversal."""

    layer = LaunchpadZopelessLayer

    def test_XpiTraversal(self):
        """Test a typical traversal of XPI file, with nested jar file."""
        xpi_content = get_en_US_xpi_file_to_import('en-US').read()
        record = TraversalRecorder('', xpi_content)
        self.assertEqual(record.traversal, [
                [
                    ('copyover1.foo', 'en-US',
                        'jar:chrome/en-US.jar!/copyover1.foo',
                        'main/copyover1.foo'
                    ),
                    ('subdir/copyover2.foo', 'en-US',
                        'jar:chrome/en-US.jar!/subdir/copyover2.foo',
                        'main/subdir/copyover2.foo'
                    ),
                    ('subdir/test2.dtd', 'en-US',
                        'jar:chrome/en-US.jar!/subdir/test2.dtd',
                        'main/subdir/test2.dtd'
                    ),
                    ('subdir/test2.properties', 'en-US',
                        'jar:chrome/en-US.jar!/subdir/test2.properties',
                        'main/subdir/test2.properties'
                    ),
                    ('test1.dtd', 'en-US',
                        'jar:chrome/en-US.jar!/test1.dtd',
                        'main/test1.dtd'
                    ),
                    ('test1.properties', 'en-US',
                        'jar:chrome/en-US.jar!/test1.properties',
                        'main/test1.properties'
                    ),
                    '.'
                ],
                '.'
            ])

    def test_WithoutManifest(self):
        """Test traversal of an XPI file without manifest."""
        xpi_content = get_en_US_xpi_file_to_import('no-manifest').read()
        record = TraversalRecorder('', xpi_content)
        # Without manifest, there is no knowledge of locale or chrome
        # paths, so those are None.
        self.assertEqual(record.traversal, [
                [
                    ('file.txt', None,
                        'jar:chrome/en-US.jar!/file.txt', None
                    ),
                    '.'
                ],
                ('no-jar.txt', None,
                    'no-jar.txt', None
                ),
                '.'
            ])


def test_suite():
    return unittest.defaultTestLoader.loadTestsFromName(__name__)

