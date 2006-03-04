# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

from zope.interface import Interface, Attribute
from canonical.launchpad.interfaces.rosettastats import IRosettaStats

__metaclass__ = type

__all__ = ('ZeroLengthPOExportError', 'IPOFileSet', 'IPOFile')


class ZeroLengthPOExportError(Exception):
    """An exception raised when a PO file export generated an empty file."""


class IPOFile(IRosettaStats):
    """A PO File."""

    id = Attribute("This PO file's id.")

    potemplate = Attribute("This PO file's template.")

    language = Attribute("Language of this PO file.")

    title = Attribute("A title for this PO file.")

    description = Attribute("PO file description.")

    topcomment = Attribute("The main comment for this .po file.")

    header = Attribute("The header of this .po file.")

    fuzzyheader = Attribute("Whether the header is fuzzy or not.")

    lasttranslator = Attribute("The last person that translated a string here.")

    license = Attribute("The license under this translation is done.")

    lastparsed = Attribute("Last time this pofile was parsed.")

    owner = Attribute("The owner for this pofile.")

    pluralforms = Attribute("The number of plural forms this PO file has.")

    variant = Attribute("The language variant for this PO file.")

    path = Attribute("The path to the file that was imported")

    exportfile = Attribute("The Librarian alias of the last cached export.")

    latest_sighting = Attribute("""Of all the translation sightings belonging
        to PO messages sets belonging to this PO file, return the one which
        was most recently modified (greatest datelastactive), or None if
        there are no sightings belonging to this PO file.""")

    datecreated = Attribute("The fate this file was created.")

    latestsubmission = Attribute("""The translation submissions which was
        most recently added, or None if there are no submissions belonging
        to this PO file.""")

    translators = Attribute("A list of Translators that have been "
        "designated as having permission to edit these files in this "
        "language.")

    contributors = Attribute("A list of all the people who have made "
        "some sort of contribution to this PO file.")

    translationpermission = Attribute("The permission system which "
        "is used for this pofile. This is inherited from the product, "
        "project and/or distro in which the pofile is found.")

    fuzzy_count = Attribute("The number of 'fuzzy' messages in this po file.")

    from_sourcepackagename = Attribute("The source package this pofile"
        " comes from (set it only if it's different from the"
        " IPOTemplate.sourcepackagenameprevious).")

    def __len__():
        """Returns the number of current IPOMessageSets in this PO file."""

    def translatedCount():
        """
        Returns the number of message sets which this PO file has current
        translations for.
        """

    def translated():
        """
        Return an iterator over translated message sets in this PO file.
        """

    def untranslatedCount():
        """
        Return the number of messages which this PO file has no translation
        for.
        """

    def untranslated():
        """
        Return an iterator over untranslated message sets in this PO file.
        """

    # Invariant: translatedCount() + untranslatedCount() = __len__()
    # XXX: add a test for this

    def __iter__():
        """Return an iterator over Current IPOMessageSets in this PO file."""

    def getPOMsgSet(msgid_text, onlyCurrent=False):
        """Return the IPOMsgSet in this IPOFile identified by msgid_text or
        None.

        :msgid_text: is an unicode string.
        :only_current: Whether we should look only on current entries.
        """

    def __getitem__(msgid_text):
        """Return the active IPOMsgSet in this IPOFile identified by msgid_text.

        :msgid_text: is an unicode string.

        Raise NotFoundError if it does not exist.
        """

    def getPOMsgSetNotInTemplate():
        """
        Return an iterator over message sets in this PO file that do not
        correspond to a message set in the template; eg, the template
        message set has sequence=0.
        """

    def getPOTMsgSetTranslated(slice=None):
        """Get pot message sets that are translated in this PO file.

        'slice' is a slice object that selects a subset of POTMsgSets.
        Return the message sets using 'slice' or all of them if slice is None.
        """

    def getPOTMsgSetFuzzy(slice=None):
        """Get pot message sets that have POMsgSet.fuzzy set in this PO file.

        'slice' is a slice object that selects a subset of POTMsgSets.
        Return the message sets using 'slice' or all of them if slice is None.
        """

    def getPOTMsgSetUntranslated(slice=None):
        """Get pot message sets that are untranslated in this PO file.

        'slice' is a slice object that selects a subset of POTMsgSets.
        Return the message sets using 'slice' or all of them if slice is None.
        """

    def getPOTMsgSetWithErrors(slice=None):
        """Get pot message sets that have translations published with errors.

        'slice' is a slice object that selects a subset of POTMsgSets.
        Return the message sets using 'slice' or all of them if slice is None.
        """

    def hasMessageID(msgid):
        """Return whether a given message ID exists within this PO file."""

    def pendingImport():
        """Gives all pofiles that have a rawfile pending of import into
        Rosetta."""

    def validExportCache():
        """Does this PO file have a cached export that is up to date?"""

    def updateExportCache(contents):
        """Update this PO file's export cache with a string."""

    def export():
        """Export this PO file as a string."""

    def exportToFileHandle(filehandle, included_obsolete=True):
        """Export this PO file to the given filehandle.

        If the included_obsolete argument is set to False, the export does not
        include the obsolete messages."""

    def uncachedExport(included_obsolete=True):
        """Export this PO file as string without using any cache.

        If included_obsolete is False, the exported PO file does not have
        obsolete entries.
        """

    def invalidateCache():
        """Invalidate the cached export."""

    def canEditTranslations(person):
        """Say if a person is able to edit existing translations.

        Return True or False indicating whether the person is allowed
        to edit these translations.
        """

    def expireAllMessages():
        """Mark our of our message sets as not current (sequence=0)"""

    def updateStatistics():
        """Update the statistics fields - rosettaCount, updatesCount and
        currentCount - from the messages currently known.
        Return a tuple (rosettaCount, updatesCount, currentCount)."""

    def createMessageSetFromMessageSet(potmsgset):
        """Creates in the database a new message set.

        Returns the newly created message set.
        """

    def createMessageSetFromText(text):
        """Creates in the database a new message set.

        Similar to createMessageSetFromMessageSet, but takes a text object
        (unicode or string) rather than a POT message Set.

        Returns the newly created message set.
        """

    def updateHeader(new_header):
        """Update the header information.

        new_header is a POHeader object.
        """

    def isPORevisionDateOlder(header):
        """Return if the given header has a less current field
        'PORevisionDate' than IPOFile.header.
        """

    def importFromQueue(logger=None):
        """Execute the import of the next entry on the queue, if needed.

        If a logger argument is given, any problem found with the
        import will be logged there.
        """


class IPOFileSet(Interface):
    """A set of POFile."""

    def getPOFilesPendingImport():
        """Return a list of PO files that have data to be imported."""

    def getDummy(potemplate, language):
        """Return a dummy pofile for the given po template and language."""

    def getPOFileByPathAndOrigin(self, path, productseries=None,
        distrorelease=None, sourcepackagename=None):
        """Return an IPOFile that is stored at 'path' in source code and
           came from the given arguments.

        Return None if there is not such IPOFile.
        """


