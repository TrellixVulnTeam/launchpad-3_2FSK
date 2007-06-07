# Copyright 2006-2007 Canonical Ltd.  All rights reserved.

from zope.interface import Interface, Attribute, Choice

from canonical.lp.dbschema import RosettaFileFormat

__metaclass__ = type

__all__ = [
    'ITranslationFormatImporter',
    'ITranslationImporter',
    'OldTranslationImported',
    'NotExportedFromLaunchpad',
    ]


class OldTranslationImported(Exception):
    """Raised when we have a newer file already imported."""


class NotExportedFromLaunchpad(Exception):
    """Raised when a file imported lacks the export time from Launchpad."""


class ITranslationImporter(Interface):
    """Interface to implement a component that handles translation imports."""

    def import_file(translation_import_queue_entry, logger=None):
        """Convert a translation resource into DB objects.

        :arg translation_import_queue_entry: An ITranslationImportQueueEntry
            entry.
        :arg logger: A logger object or None.

        If the entry is older than previous imported file,
        OldTranslationImported exception is raised.

        If the entry imported is not published and doesn't have the tag added
        by Launchpad on export time, NotExportedFromLaunchpad exception is
        raised.

        Return a list of dictionaries with three keys:
            - 'pomsgset': The DB pomsgset with an error.
            - 'pomessage': The original POMessage object.
            - 'error-message': The error message as gettext names it.
        """


class ITranslationFormatImporter(Interface):
    """Translation file importer."""

    allentries = Attribute(
        'List of Templates and translations provided by this file.')

    format = Choice(
        title=u'The file format of the import.',
        values=RosettaFileFormat.items,
        required=True)

    def canHandleFileExtension(extension):
        """Whether this importer is able to handle the given file extension.

        :arg extension: File extension"""

    def getTemplate(path):
        """Return a dictionary representing a translation template.

        :arg path: Location of the template.
        """

    def getTranslation(path, language):
        """Return a dictionary representing a translation.

        :arg path: Location of the translation.
        :arg language: Language we are interested on.
        """
