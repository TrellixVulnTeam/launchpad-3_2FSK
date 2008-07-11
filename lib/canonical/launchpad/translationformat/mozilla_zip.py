# Copyright 2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'MozillaZipFile',
    ]

from StringIO import StringIO
from zipfile import ZipFile

from canonical.launchpad.translationformat.xpi_header import XpiHeader
from canonical.launchpad.translationformat.xpi_manifest import (
    make_jarpath, XpiManifest)


class MozillaZipFile:
    """Traversal of an XPI file, or a jar file inside an XPI file.

    To traverse and process an XPI file, derive a class from this one
    and replace any hooks that you may need.

    If an XPI manifest is provided, traversal will be restricted to
    directories it lists as containing localizable resources.
    """

    def __init__(self, filename, content, xpi_path=None, manifest=None):
        """Open zip (or XPI, or jar) file and scan its contents.

        :param filename: Name of this zip (XPI/jar) file.
        :param content: The data making up this zip file.
        :param xpi_path: Full path of this file inside the XPI archive.
            Leave out for the XPI file itself.
        :param manifest: `XpiManifest` representing the XPI archive's
            manifest file, if any.
        """
        self.filename = filename
        self.header = None
        self.last_translator = None
        self.manifest = manifest
        self.archive = ZipFile(StringIO(content), 'r')

        if xpi_path is None:
            # This is the main XPI file.
            xpi_path = ''
            contained_files = set(self.archive.namelist())
            if manifest is None:
                # Look for a manifest.
                for filename in ['chrome.manifest', 'en-US.manifest']:
                    if filename in contained_files:
                        manifest_content = self.archive.read(filename)
                        self.manifest = XpiManifest(manifest_content)
                        break
            if 'install.rdf' in contained_files:
                rdf_content = self.archive.read('install.rdf')
                self.header = XpiHeader(rdf_content)

        # Strip trailing newline to avoid doubling it.
        if xpi_path.endswith('/'):
            xpi_path = xpi_path[:-1]

        self._begin()

        # Process zipped files.  Sort by path to keep ordering deterministic.
        # Ordering matters in sequence numbering (which in turn shows up in
        # the UI), but also for consistency in duplicates resolution and for
        # automated testing.
        for entry in sorted(self.archive.namelist()):
            self._processEntry(entry, xpi_path)

        self._complete()

    def _begin(self):
        """Overridable hook: pre-traversal actions."""

    def _process(self, entry, locale_code, xpi_path, chrome_path):
        """Overridable hook: process a file entry.

        Called only for files that may be localizable.  If there is a
        manifest, that means the file must be in a location (or subtree)
        named by a "locale" entry.

        :param entry: Full name of file inside this zip archive,
            including path relative to the archive's root.
        :param locale_code: Code for locale this file belongs to, e.g.
            "en-US".
        :param xpi_path: Full path of this file inside the XPI archive,
            e.g. "jar:locale/en-US.jar!/data/messages.dtd".
        :param chrome_path: File's chrome path.  This is a kind of
            "normalized" path used in XPI to describe a virtual
            directory hierarchy.  The zip archive's actual layout (which
            the XPI paths describe) may be different.
        """

    def _descend(self, entry, content, xpi_path):
        """Overridable hook: descend into jar file.

        Default implementation recurses by creating a new instance of
        the same `MozillaZipFile` implementation.

        Any value returned by this method will be passed to a matching
        invocation of `_emerge`, which backtracks the recursion.

        :param entry: Full name of jar file inside this zip archive.
        :param content: Bytes of this jar file.
        :param xpi_path: Base XPI path for jar file.  Prefix this to an
            entry in the jar file to get the entry's full XPI path.

        :return: In the default implementation, an instance of the same
            class as self, but one that traverses the jar file.
        """
        return self.__class__(filename=entry, xpi_path=xpi_path,
            content=content, manifest=self.manifest)

    def _emerge(self, descend_result):
        """Overridable hook: return from descent into jar file.

        :param descend_result: return value from matching `_descend`().
        """

    def _complete(self):
        """Overridable hook: post-traveral actions."""

    def _processEntry(self, entry, xpi_path):
        """Read one zip archive entry, figure out what to do with it."""
        is_jar = entry.endswith('.jar')

        if is_jar:
            jarpath = make_jarpath(xpi_path, entry)
            if not self.manifest or self.manifest.containsLocales(jarpath):
                # If this is a jar file that may contain localizable
                # resources, don't process it in the normal way; descend into
                # it.
                content = self.archive.read(entry)
                self._emerge(self._descend(entry, content, jarpath))
                return

        xpi_path = "%s/%s" % (xpi_path, entry)
        if self.manifest is None:
            # No manifest, so we don't have chrome paths.  Process
            # everything just to be sure.
            chrome_path = None
            locale_code = None
        else:
            chrome_path, locale_code = self.manifest.getChromePathAndLocale(
                xpi_path)
            if chrome_path is None:
                # Not in a directory containing localizable resources.
                return

        self._process(entry, locale_code, xpi_path, chrome_path)

