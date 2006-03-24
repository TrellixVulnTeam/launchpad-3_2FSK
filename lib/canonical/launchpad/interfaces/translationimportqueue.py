# Copyright 2005 Canonical Ltd. All rights reserved.

from zope.interface import Interface, Attribute
from zope.schema import Bool, Choice, TextLine, Datetime, Field

from canonical.lp.dbschema import RosettaImportStatus

from zope.i18nmessageid import MessageIDFactory
_ = MessageIDFactory('launchpad')

__metaclass__ = type

__all__ = [
    'ITranslationImportQueueEntry',
    'ITranslationImportQueue',
    'IEditTranslationImportQueueEntry',
    ]

class ITranslationImportQueueEntry(Interface):
    """An entry of the Translation Import Queue."""

    id = Attribute('The entry ID')

    path = TextLine(
        title=_("Path"),
        description=_(
            "The path to this file inside the source tree. Includes the"
            " filename."),
        required=True)

    importer = Choice(
        title=_("Importer"),
        required=True,
        description=_(
            "The person that imported this file in Rosetta."),
        vocabulary="ValidOwner")

    dateimported = Attribute('The timestamp when this file was imported.')

    productseries = Choice(
        title=_("Product Branch or Series"),
        required=False,
        vocabulary="ProductSeries")

    distrorelease = Choice(
        title=_("Distribution Release"),
        required=False,
        vocabulary="DistroRelease")

    sourcepackagename = Choice(
        title=_("Source Package Name"),
        description=_(
            "The source package from where this entry comes."),
        required=False,
        vocabulary="SourcePackageName")

    is_published = Bool(
        title=_("This import comes from a published file"),
        description=_(
            "If checked, this import will be handled as already published."),
        required=True,
        default=False)

    content = Attribute(
        "An ILibraryFileAlias reference with the file content. Must be not"
        " None.")

    # XXX CarlosPerelloMarin 20060301: We are using Choice instead of Attribute
    # due bug #34103
    status = Choice(
        title=_("The status of the import."),
        values=RosettaImportStatus.items,
        required=True)

    date_status_changed = Datetime(
        title=_("The timestamp when the status was changed."),
        required=True)

    sourcepackage = Attribute("The sourcepackage associated with this entry.")

    guessed_potemplate = Attribute(
        "The IPOTemplate that we can guess this entry could be imported into."
        " None if we cannot guess it.")

    guessed_language_and_variant = Attribute(
        "A set with the ILanguage and a variant that we think this entry is"
        "for.")

    guessed_pofile = Attribute(
        "The IPOFile that we can guess this entry could be imported into."
        " None if we cannot guess it.")

    import_into = Attribute("The Object where this entry will be imported. Is"
        " None if we don't know where to import it.")

    # XXX CarlosPerelloMarin 20060301: We are using Field instead of Attribute
    # due bug #34103
    pofile = Field(
        title=_("The IPOfile where this entry should be imported."),
        required=False)

    # XXX CarlosPerelloMarin 20060301: We are using Field instead of Attribute
    # due bug #34103
    potemplate = Field(
        title=_("The IPOTemplate associated with this entry."),
        description=_("The IPOTemplate associated with this entry. If path"
        " notes a .pot file, it should be used as the place where this entry"
        " will be imported, if it's a .po file, it indicates the template"
        " associated with tha translation."),
        required=False)

    def getFileContent():
        """Return the imported file content as a stream."""


class ITranslationImportQueue(Interface):
    """A set of files to be imported into Rosetta."""

    def __iter__():
        """Iterate over all entries in the queue."""

    def __getitem__(id):
        """Return the ITranslationImportQueueEntry with the given id.

        If there is not entries with that id, the NotFoundError exception is
        raised.
        """

    def __len__():
        """Return the number of entries in the queue, including blocked
        entries.
        """

    def iterNeedReview():
        """Iterate over all entries in the queue that need review."""

    def addOrUpdateEntry(path, content, is_published, importer,
        sourcepackagename=None, distrorelease=None, productseries=None,
        potemplate=None):
        """Return a new or updated entry of the import queue.

        :arg path: is the path, with the filename, of the file imported.
        :arg content: is the file content.
        :arg is_published: indicates if the imported file is already published
            by upstream.
        :arg importer: is the person that did the import.
        :arg sourcepackagename: is the link of this import with source
            package.
        :arg distrorelease: is the link of this import with a distribution.
        :arg productseries: is the link of this import with a product branch.
        :arg potemplate: is the link of this import with an IPOTemplate.

        sourcepackagename + distrorelease and productseries are exclusive, we
        must have only one combination of them.
        """

    def addOrUpdateEntriesFromTarball(content, is_published, importer,
        sourcepackagename=None, distrorelease=None, productseries=None,
        potemplate=None):
        """Add all .po or .pot files from the tarball at :content:.

        :arg content: is a tarball stream.
        :arg is_published: indicates if the imported file is already published
            by upstream.
        :arg importer: is the person that did the import.
        :arg sourcepackagename: is the link of this import with source
            package.
        :arg distrorelease: is the link of this import with a distribution.
        :arg productseries: is the link of this import with a product branch.
        :arg potemplate: is the link of this import with an IPOTemplate.

        sourcepackagename + distrorelease and productseries are exclusive, we
        must have only one combination of them.

        Return the number of files attached.
        """

    def get(id):
        """Return the ITranslationImportQueueEntry with the given id or None.
        """

    def getAllEntries(status=None, file_extension=None):
        """Return all entries this import queue has

        :arg status: RosettaImportStatus entry.
        :arg file_extension: String with the file type extension, usually 'po'
            or 'pot'.

        If either status or file_extension are given, the returned entries are
        filtered based on those values.
        """

    def getFirstEntryToImport():
        """Return the first entry of the queue ready to be imported."""

    def getEntriesWithPOTExtension(
        distrorelease=None, sourcepackagename=None, productseries=None):
        """Return all entries with the '.pot' extension in the path field.

        distrorelease, sourcepackagename and productseries can be used for
        filtering purposes.
        """

    def executeAutomaticReviews(ztm):
        """Try to move entries from the Needs Review status to Approved one.

        :arg ztm: Zope transaction manager object.

        This method moves all entries that we know where should they be
        imported from the Needs Review status to the Accepted one.
        """

    def cleanUpQueue():
        """Remove old DELETED and IMPORTED entries.

        Only entries older than 5 days will be removed.
        """

    def remove(entry):
        """Remove the given :entry: from the queue."""


class IEditTranslationImportQueueEntry(Interface):
    """Set of widgets needed to moderate an entry on the imports queue."""

    potemplatename = Choice(
        title=_("Template Name"),
        description=_("The name of this PO template, for example "
            "'evolution-2.2'. Each translation template has a "
            "unique name in its package. It's important to get this "
            "correct, because Rosetta will recommend alternative "
            "translations based on the name."),
        required=True,
        vocabulary="POTemplateName")

    sourcepackagename = Choice(
        title=_("Source Package Name"),
        description=_(
            "The source package from where this entry comes."),
        required=True,
        vocabulary="SourcePackageName")

    language = Choice(
        title=_("Language"),
        required=False,
        vocabulary="Language")

    variant = TextLine(
        title=_("Variant"),
        required=False)

    path = TextLine(
        title=_("Path"),
        description=_(
            "The path to this file inside the source tree. If it's empty, we"
            " use the one from the queue entry."),
        required=False)
