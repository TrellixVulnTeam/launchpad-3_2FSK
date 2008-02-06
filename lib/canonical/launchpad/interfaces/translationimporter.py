# Copyright 2006-2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Interfaces to handle translation files imports."""

__metaclass__ = type

__all__ = [
    'ITranslationFormatImporter',
    'ITranslationImporter',
    'OutdatedTranslationError',
    'NotExportedFromLaunchpad',
    'TooManyPluralFormsError',
    'TranslationFormatSyntaxError',
    'TranslationFormatInvalidInputError',
    ]

from zope.interface import Interface
from zope.schema import Bool, Int, List, TextLine

from canonical.launchpad.interfaces.translationcommonformat import (
    TranslationImportExportBaseException)


class OutdatedTranslationError(TranslationImportExportBaseException):
    """A newer file has already been imported."""


class NotExportedFromLaunchpad(TranslationImportExportBaseException):
    """An imported file lacks the Launchpad export time."""


class TooManyPluralFormsError(TranslationImportExportBaseException):
    """Translation defines more plural forms than we can handle."""


class TranslationFormatBaseError(TranslationImportExportBaseException):
    """Base exception for errors in translation format files."""

    def __init__(self, filename=None, line_number=None, message=None):
        """Initialise the exception information.

        :param filename: The file name that is being parsed.
        :param line_number: The line number where the error was found.
        :param message: The concrete syntax error found. If we get a not None
            value here, filename and line_number are ignored.
        """
        TranslationImportExportBaseException.__init__(self, message)

        self.filename = filename
        self.line_number = line_number
        self.message = message

    def represent(self, default_message):
        """Return human-readable description of error location."""
        if self.filename is not None:
            safe_filename = self.filename.encode("ascii", "backslashreplace")

        if self.line_number is not None and self.line_number > 0:
            if self.filename is not None:
                location = "%s, line %d" % (safe_filename, self.line_number)
            else:
                location = "Line %d" % self.line_number
        elif self.filename is not None:
            location = safe_filename
        else:
            location = None

        if location is not None:
            location_prefix = "%s: " % location
        else:
            location_prefix = ""

        if self.message is not None:
            text = self.message.encode("ascii", "backslashreplace")
        else:
            text = default_message

        return "%s%s" % (location_prefix, text)


class TranslationFormatSyntaxError(TranslationFormatBaseError):
    """A syntax error occurred while parsing a translation file."""

    def __str__(self):
        return self.represent("Unknown syntax error")


class TranslationFormatInvalidInputError(TranslationFormatBaseError):
    """Some fields in the parsed file contain bad content."""

    def __str__(self):
        return self.represent("Invalid input")


class ITranslationImporter(Interface):
    """Importer of translation files."""

    supported_file_extensions = List(
        title=u'List of file extensions we have imports for.',
        required=True, readonly=True)

    def getTranslationFileFormat(file_extension, file_contents):
        """Return the translation file format for the given file extension.

        :param file_extension: File extension including the dot.
        :param file_contents: File contents.
        :return: A `TranslationFileFormat` for the given file extension
            and file contents or None if it's not supported format.
        """

    def getTranslationFormatImporter(file_format):
        """Return the translation format importer for the given file format.

        :param file_format: A TranslationFileFormat entry.
        :return: An `ITranslationFormatImporter` or None if there is no
            handler for the given file format.
        """

    def importFile(translation_import_queue_entry):
        """Import an `ITranslationImportQueueEntry` file into the system.

        :param translation_import_queue_entry: An
            `ITranslationImportQueueEntry` entry.
        :raise OutdatedTranslationError: If the entry is older than the
            previously imported file.
        :raise NotExportedFromLaunchpad: If the entry imported is not
            published and doesn't have the tag added by Launchpad on export
            time.
        :return: a list of dictionaries with all errors found. Each dictionary
            has three keys:
            - 'pomsgset': An `IPOMsgSet` associated with this error.
            - 'pomessage': The original message text in its native format.
            - 'error-message': The error message text.
        """


class ITranslationFormatImporter(Interface):
    """Translation file format importer."""

    def getFormat(file_contents):
        """The file format of the import.

        :param file_contents: A unicode string with the contents of the file
            being imported.  A returned format may sometimes be different
            from the base format of the `ITranslationFormatImporter`, and
            that is determined based on the `contents`.
        :return: A `TranslationFileFormat` value.
        """

    priority = Int(
        title=u'Priority among importers for the same file extension.',
        description=u'''
            Priority an `ITranslationFormatImporter` has if there are
            multiple importers for the same file extension.

            Higher value indicates higher priority, i.e. that importer
            is tried first.
            ''',
        required=True,
        default=0
        )

    content_type = TextLine(
        title=u'Content type string for this file format.',
        required=True, readonly=True)

    file_extensions = List(
        title=u'File extensions handable by this importer.',
        required=True, readonly=True)

    uses_source_string_msgids = Bool(
        title=u'A flag indicating whether uses source string as the id',
        description=u'''
            A flag indicating whether this file format importer uses source
            string msgids as the English strings.
            ''',
        required=True, readonly=True)

    def parse(translation_import_queue_entry):
        """Parse an `ITranslationImportQueueEntry` into an
        `ITranslationFileData`.

        :param translation_import_queue: An `ITranslationImportQueueEntry` to
            parse.
        :return: An `ITranslationFileData` representing the parsed file.
        """

    def getHeaderFromString(header_string):
        """Return the `ITranslationHeaderData` for the given header string.

        :param header_string: A text representing a header for this concrete
            file format.
        :return: An `ITranslationHeaderData` based on the header string.
        """
