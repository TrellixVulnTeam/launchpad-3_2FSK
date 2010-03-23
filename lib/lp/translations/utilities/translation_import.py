# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'TranslationImporter',
    'importers',
    'is_identical_translation',
    ]

import gettextpo
import datetime
import posixpath
import pytz
from zope.component import getUtility
from zope.interface import implements

from operator import attrgetter

import transaction

from canonical.config import config
from canonical.database.sqlbase import cursor, quote

from storm.exceptions import TimeoutError

from canonical.cachedproperty import cachedproperty
from lp.registry.interfaces.person import (
    IPersonSet,
    PersonCreationRationale)
from lp.translations.interfaces.translationexporter import (
    ITranslationExporter)
from lp.translations.interfaces.translationimporter import (
    ITranslationImporter,
    NotExportedFromLaunchpad,
    OutdatedTranslationError)
from lp.translations.interfaces.translationimportqueue import (
    RosettaImportStatus)
from lp.translations.interfaces.translationmessage import (
    TranslationConflict)
from lp.translations.interfaces.translationfileformat import (
    TranslationFileFormat)
from lp.translations.interfaces.translations import (
    TranslationConstants)
from canonical.launchpad.interfaces.emailaddress import InvalidEmailAddress
from lp.translations.utilities.kde_po_importer import (
    KdePOImporter)
from lp.translations.utilities.gettext_po_importer import (
    GettextPOImporter)
from lp.translations.utilities.mozilla_xpi_importer import (
    MozillaXpiImporter)
from lp.translations.utilities.translation_common_format import (
    TranslationMessageData)

from canonical.launchpad.webapp import canonical_url


importers = {
    TranslationFileFormat.KDEPO: KdePOImporter(),
    TranslationFileFormat.PO: GettextPOImporter(),
    TranslationFileFormat.XPI: MozillaXpiImporter(),
    }


def is_identical_translation(existing_msg, new_msg):
    """Is a new translation substantially the same as the existing one?

    Compares msgid and msgid_plural, and all translations.

    :param existing_msg: a `TranslationMessageData` representing a translation
        message currently kept in the database.
    :param new_msg: an alternative `TranslationMessageData` translating the
        same original message.
    :return: True if the new message is effectively identical to the
        existing one, or False if replacing existing_msg with new_msg
        would make a semantic difference.
    """
    assert new_msg.msgid_singular == existing_msg.msgid_singular, (
        "Comparing translations for different messages.")

    if (existing_msg.msgid_plural != new_msg.msgid_plural):
        return False
    if len(new_msg.translations) < len(existing_msg.translations):
        return False
    length_overlap = min(
        len(existing_msg.translations), len(new_msg.translations))
    for pluralform_index in xrange(length_overlap):
        # Plural forms that both messages have.  Translations for each
        # must match.
        existing_text = existing_msg.translations[pluralform_index]
        new_text = new_msg.translations[pluralform_index]
        if existing_text != new_text:
            return False
    for pluralform_index in xrange(length_overlap, len(new_msg.translations)):
        # Plural forms that exist in new_translations but not in
        # existing_translations.  That's okay, as long as all of them are
        # None.
        if new_msg.translations[pluralform_index] is not None:
            return False
    return True


class ExistingPOFileInDatabase:
    """All existing translations for a PO file.

    Fetches all information needed to compare messages to be imported in one
    go. Used to speed up PO file import."""

    def __init__(self, pofile, is_current_upstream=False):
        self.pofile = pofile
        self.is_current_upstream = is_current_upstream

        # Dict indexed by (msgid, context) containing current
        # TranslationMessageData: doing this for the speed.
        self.ubuntu_messages = {}
        # Messages which have been seen in the file: messages which exist
        # in the database, but not in the import, will be expired.
        self.seen = set()

        # Contains upstream but inactive translations.
        self.upstream_messages = {}

        # Pre-fill self.ubuntu_messages and self.upstream_messages with data.
        self._fetchDBRows()

    def _fetchDBRows(self):
        msgstr_joins = [
            "LEFT OUTER JOIN POTranslation pt%d "
            "ON pt%d.id = TranslationMessage.msgstr%d" % (form, form, form)
            for form in xrange(TranslationConstants.MAX_PLURAL_FORMS)]

        translations = [
            "pt%d.translation AS translation%d" % (form, form)
            for form in xrange(TranslationConstants.MAX_PLURAL_FORMS)]

        substitutions = {
            'translation_columns': ', '.join(translations),
            'translation_joins': '\n'.join(msgstr_joins),
            'language': quote(self.pofile.language),
            'variant': quote(self.pofile.variant),
            'potemplate': quote(self.pofile.potemplate),
        }

        sql = '''
        SELECT
            POMsgId.msgid AS msgid,
            POMsgID_Plural.msgid AS msgid_plural,
            context,
            date_reviewed,
            is_current_ubuntu,
            is_current_upstream,
            %(translation_columns)s
          FROM POTMsgSet
            JOIN TranslationTemplateItem ON
              TranslationTemplateItem.potmsgset = POTMsgSet.id AND
              TranslationTemplateItem.potemplate = %(potemplate)s
            JOIN TranslationMessage ON
              POTMsgSet.id=TranslationMessage.potmsgset AND
              (TranslationMessage.potemplate = %(potemplate)s OR
               TranslationMessage.potemplate IS NULL) AND
              TranslationMessage.language = %(language)s AND
              TranslationMessage.variant IS NOT DISTINCT FROM %(variant)s
            %(translation_joins)s
            JOIN POMsgID ON
              POMsgID.id=POTMsgSet.msgid_singular
            LEFT OUTER JOIN POMsgID AS POMsgID_Plural ON
              POMsgID_Plural.id=POTMsgSet.msgid_plural
          WHERE
              (is_current_ubuntu IS TRUE OR is_current_upstream IS TRUE)
          ORDER BY
            TranslationTemplateItem.sequence,
            TranslationMessage.potemplate NULLS LAST
          ''' % substitutions

        cur = cursor()
        try:
            # XXX 2009-09-14 DaniloSegan (bug #408718):
            # this statement causes postgres to eat the diskspace
            # from time to time.  Let's wrap it up in a timeout.
            timeout = config.poimport.statement_timeout

            # We have to commit what we've got so far or we'll lose
            # it when we hit TimeoutError.
            transaction.commit()

            if timeout == 'timeout':
                # This is used in tests.
                query = "SELECT pg_sleep(2)"
                timeout = '1s'
            else:
                timeout = 1000 * int(timeout)
                query = sql
            cur.execute("SET statement_timeout to %s" % quote(timeout))
            cur.execute(query)
        except TimeoutError:
            # Restart the transaction and return empty SelectResults.
            transaction.abort()
            transaction.begin()
            cur.execute("SELECT 1 WHERE 1=0")
        rows = cur.fetchall()

        assert TranslationConstants.MAX_PLURAL_FORMS == 6, (
            "Change this code to support %d plural forms"
            % TranslationConstants.MAX_PLURAL_FORMS)
        for (msgid, msgid_plural, context, date, is_current_ubuntu,
             is_current_upstream, msgstr0, msgstr1, msgstr2, msgstr3, msgstr4,
             msgstr5) in rows:

            if not is_current_ubuntu and not is_current_upstream:
                # We don't care about non-current and non-imported messages
                # yet.  To be part of super-fast-imports-phase2.
                continue

            update_caches = []
            if is_current_ubuntu:
                update_caches.append(self.ubuntu_messages)
            if is_current_upstream:
                update_caches.append(self.upstream_messages)

            for look_at in update_caches:
                if (msgid, msgid_plural, context) in look_at:
                    message = look_at[(msgid, msgid_plural, context)]
                else:
                    message = TranslationMessageData()
                    look_at[(msgid, msgid_plural, context)] = message

                    message.context = context
                    message.msgid_singular = msgid
                    message.msgid_plural = msgid_plural

                for plural in range(TranslationConstants.MAX_PLURAL_FORMS):
                    local_vars = locals()
                    msgstr = local_vars.get('msgstr' + str(plural), None)
                    if (msgstr is not None and
                        ((len(message.translations) > plural and
                          message.translations[plural] is None) or
                         (len(message.translations) <= plural))):
                        message.addTranslation(plural, msgstr)

    def markMessageAsSeen(self, message):
        """Marks a message as seen in the import, to avoid expiring it."""
        self.seen.add((message.msgid_singular, message.msgid_plural,
                       message.context))

    def getUnseenMessages(self):
        """Return a set of messages present in the database but not seen
        in the file being imported.
        """
        unseen = set()
        for (singular, plural, context) in self.ubuntu_messages:
            if (singular, plural, context) not in self.seen:
                unseen.add((singular, plural, context))
        for (singular, plural, context) in self.upstream_messages:
            if ((singular, plural, context) not in self.ubuntu_messages and
                (singular, plural, context) not in self.seen):
                unseen.add((singular, plural, context))
        return unseen

    def isAlreadyTranslatedTheSameInUbuntu(self, message):
        """Check whether this message is already translated in exactly
        the same way.
        """
        (msgid, plural, context) = (message.msgid_singular,
                                    message.msgid_plural,
                                    message.context)
        if (msgid, plural, context) in self.ubuntu_messages:
            msg_in_db = self.ubuntu_messages[(msgid, plural, context)]
            return is_identical_translation(msg_in_db, message)
        else:
            return False

    def isAlreadyTranslatedTheSameUpstream(self, message):
        """Is this translation already the current upstream one?

        If this translation is already present in the database as the
        'is_current_upstream' translation, and we are processing an
        upstream upload, it does not need changing.
        """
        (msgid, plural, context) = (message.msgid_singular,
                                    message.msgid_plural,
                                    message.context)
        is_existing_upstream = (
            (msgid, plural, context) in self.upstream_messages)
        if is_existing_upstream and self.is_current_upstream:
            msg_in_db = self.upstream_messages[(msgid, plural, context)]
            return is_identical_translation(msg_in_db, message)
        else:
            return False


class TranslationImporter:
    """Handle translation resources imports."""

    implements(ITranslationImporter)

    @cachedproperty
    def supported_file_extensions(self):
        """See `ITranslationImporter`."""
        file_extensions = []

        for importer in importers.itervalues():
            file_extensions.extend(importer.file_extensions)

        return sorted(set(file_extensions))

    @cachedproperty
    def template_suffixes(self):
        """See `ITranslationImporter`."""
        # Several formats (particularly the various gettext variants) can have
        # the same template suffix.
        unique_suffixes = set(
            importer.template_suffix for importer in importers.values())
        return sorted(unique_suffixes)

    def isTemplateName(self, path):
        """See `ITranslationImporter`."""
        for importer in importers.itervalues():
            if path.endswith(importer.template_suffix):
                return True
        return False

    def isHidden(self, path):
        """See `ITranslationImporter`."""
        normalized_path = posixpath.normpath(path)
        return normalized_path.startswith('.') or '/.' in normalized_path

    def isTranslationName(self, path):
        """See `ITranslationImporter`."""
        base_name, suffix = posixpath.splitext(path)
        if suffix not in self.supported_file_extensions:
            return False
        for importer_suffix in self.template_suffixes:
            if path.endswith(importer_suffix):
                return False
        return True

    def getTranslationFileFormat(self, file_extension, file_contents):
        """See `ITranslationImporter`."""
        all_importers = importers.values()
        all_importers.sort(key=attrgetter('priority'), reverse=True)
        for importer in all_importers:
            if file_extension in importer.file_extensions:
                return importer.getFormat(file_contents)

        return None

    def getTranslationFormatImporter(self, file_format):
        """See `ITranslationImporter`."""
        return importers.get(file_format, None)

    def importFile(self, translation_import_queue_entry, logger=None):
        """See ITranslationImporter."""
        assert translation_import_queue_entry is not None, (
            "The translation import queue entry cannot be None.")
        assert (translation_import_queue_entry.status ==
                RosettaImportStatus.APPROVED), (
                "The entry is not approved!.")
        assert (translation_import_queue_entry.potemplate is not None or
                translation_import_queue_entry.pofile is not None), (
                "The entry has not any import target.")

        importer = self.getTranslationFormatImporter(
            translation_import_queue_entry.format)
        assert importer is not None, (
            'There is no importer available for %s files' % (
                translation_import_queue_entry.format.name))

        # Select the import file type.
        if translation_import_queue_entry.pofile is None:
            # Importing a translation template (POT file).
            file_importer = POTFileImporter(
                translation_import_queue_entry, importer, logger)
        else:
            # Importing a translation (PO file).
            file_importer = POFileImporter(
                translation_import_queue_entry, importer, logger)

        # Do the import and return the errors.
        return file_importer.importFile()


class FileImporter(object):
    """Base class for importing translations or translation templates.

    This class is meant to be subclassed for the specialised tasks of
    importing translations (PO)or translation templates (POT) respectively.
    Subclasses need to implement the importMessage method and extend
    the constructor to set self.pofile and self.potemplate correctly.
    """

    def __init__(self, translation_import_queue_entry,
                 importer, logger = None):
        """Base constructor to set up common attributes and parse the imported
        file into a member variable (self.translation_file).

        Subclasses must extend this constructor to set the default values
        according to their needs, most importantly self.pofile and
        self.potemplate.

        :param translation_import_queue_entry: The queue entry, as has been
            provided to TranslationImporter.importFile.
        :param importer: The importer to use for parsing the file.
        :param logger: An optional logger.
        """

        self.translation_import_queue_entry = translation_import_queue_entry
        self.importer = importer
        self.logger = logger

        # These two must be set correctly by the derived classes.
        self.pofile = None
        self.potemplate = None

        self._cached_format_exporter = None

        # Parse the file using the importer.
        self.translation_file = importer.parse(
            translation_import_queue_entry)

        self.is_editor = False
        self.last_translator = None
        self.lock_timestamp = None
        self.pofile_in_db = None
        self.errors = []

    def getOrCreatePOTMsgSet(self, message):
        """Get the POTMsgSet that this message belongs to or create a new
        one if none was found.

        :param message: The message.
        :return: The POTMsgSet instance, existing or new.
        """
        potmsgset = (
            self.potemplate.getOrCreateSharedPOTMsgSet(
                message.msgid_singular, plural_text=message.msgid_plural,
                context=message.context))
        return potmsgset

    def storeTranslationsInDatabase(self, message, potmsgset):
        """Try to store translations in the database.

        Perform check if a PO file is available and if the message has any
        translations that can be stored. If an exception is caught, an error
        is added to the list in self.errors but the translations are stored
        anyway, marked as having an error.

        :param message: The message who's translations will be stored.
        :param potmsgset: The POTMsgSet that this message belongs to.

        :return: The updated translation_message entry or None, if no storing
            war done.
        """
        if self.pofile is None:
            # It's neither an IPOFile nor an IPOTemplate that needs to
            # store English strings in an IPOFile.
            return None

        if not message.translations:
            # We don't have anything to import.
            return None

        try:
            # Do the actual import.
            translation_message = potmsgset.updateTranslation(
                self.pofile, self.last_translator, message.translations,
                self.translation_import_queue_entry.from_upstream,
                self.lock_timestamp, force_edition_rights=self.is_editor)
        except TranslationConflict:
            self._addConflictError(message, potmsgset)
            if self.logger is not None:
                self.logger.info(
                    "Conflicting updates on message %d." % potmsgset.id)
            return None
        except gettextpo.error, e:
            # We got an error, so we submit the translation again but
            # this time asking to store it as a translation with
            # errors.

            # Add the pomsgset to the list of pomsgsets with errors.
            self._addUpdateError(message, potmsgset, unicode(e))

            try:
                translation_message = potmsgset.updateTranslation(
                    self.pofile, self.last_translator, message.translations,
                    self.translation_import_queue_entry.from_upstream,
                    self.lock_timestamp, ignore_errors=True,
                    force_edition_rights=self.is_editor)
            except TranslationConflict:
                # A conflict on top of a validation error?  Give up.
                # This message is cursed.
                if self.logger is not None:
                    self.logger.info(
                        "Conflicting updates; ignoring invalid message %d." %
                            potmsgset.id)
                return None


        just_replaced_msgid = (
            self.importer.uses_source_string_msgids and
            self.pofile.language.code == 'en')
        if just_replaced_msgid:
            potmsgset.clearCachedSingularText()

        return translation_message

    def importMessage(self, message):
        """Import a single message.

        This method must be implemented by the derived class to perform all
        necessary steps to import a single message into the database.

        :param message: The message to be imported.

        :raise NotImplementedError: if no implementation is provided.
        """
        raise NotImplementedError

    def finishImport(self):
        """Perform finishing steps after all messages have been imported.

        This method may be implemented by the derived class, if such steps
        are necessary.
        """

    def importFile(self):
        """Import a parsed file into the database.

        Loop through all message entries in the parsed file and import them
        using the importMessage.

        :return: The errors encountered during the import.
        """
        # Collect errors here.
        self.errors = []

        for message in self.translation_file.messages:
            if not message.msgid_singular:
                # The message has no msgid, we ignore it and jump to next
                # message.
                continue

            self.importMessage(message)

        self.finishImport()

        return self.errors, self.translation_file.syntax_warnings

    @property
    def format_exporter(self):
        """Get the exporter to display a message in error messages."""
        if self._cached_format_exporter is None:
            self._cached_format_exporter = getUtility(
                  ITranslationExporter).getExporterProducingTargetFileFormat(
                        self.translation_import_queue_entry.format)
        return self._cached_format_exporter


    def _addUpdateError(self, message, potmsgset, errormsg):
        """Add an error returned by updateTranslation.

        This has been put in a method enhance clarity by removing the long
        error text from the calling method.

        :param message: The current message from the translation file.
        :param potmsgset: The current messageset for this message id.
        :param errormsg: The errormessage returned by updateTranslation.
        """
# XXX: henninge 2008-11-05: The error should contain an ID of some sort
#  to provide an explicit identification in tests. Until then error messages
#  must not be rephrased without changing the test as well.
        self.errors.append({
            'potmsgset': potmsgset,
            'pofile': self.pofile,
            'pomessage': self.format_exporter.exportTranslationMessageData(
                message),
            'error-message': unicode(errormsg)
        })

    def _addConflictError(self, message, potmsgset):
        """Add an error if there was an edit conflict.

        This has been put in a method enhance clarity by removing the long
        error text from the calling method.

        :param message: The current message from the translation file.
        :param potmsgset: The current messageset for this message id.
        """
        self._addUpdateError(message, potmsgset,
            "This message was updated by someone else after you"
            " got the translation file. This translation is now"
            " stored as a suggestion, if you want to set it as"
            " the used one, go to %s/+translate and approve"
            " it." % canonical_url(self.pofile))


class POTFileImporter(FileImporter):
    """Import a translation template file."""

    def __init__(self, translation_import_queue_entry, importer, logger):
        """Construct an Importer for a translation template."""

        assert(translation_import_queue_entry.pofile is None,
            "Pofile must be None when importing a template.")

        # Call base constructor
        super(POTFileImporter, self).__init__(
             translation_import_queue_entry, importer, logger)

        self.pofile = None
        self.potemplate = translation_import_queue_entry.potemplate

        self.potemplate.source_file_format = (
            translation_import_queue_entry.format)
        self.potemplate.source_file = (
            translation_import_queue_entry.content)
        if self.importer.uses_source_string_msgids:
            # We use the special 'en' language as the way to store the
            # English strings to show instead of the msgids.
            self.pofile = self.potemplate.getPOFileByLang('en')
            if self.pofile is None:
                self.pofile = self.potemplate.newPOFile('en')

        # Expire old messages.
        self.potemplate.expireAllMessages()
        if self.translation_file.header is not None:
            # Update the header.
            self.potemplate.header = (
                self.translation_file.header.getRawContent())
        UTC = pytz.timezone('UTC')
        self.potemplate.date_last_updated = datetime.datetime.now(UTC)

        # By default translation template uploads are done only by
        # editors.
        self.is_editor = True
        self.last_translator = (
            translation_import_queue_entry.importer)

        # Messages are counted to maintain the original sequence.
        self.count = 0

    def importMessage(self, message):
        """See FileImporter."""
        self.count += 1

        if 'fuzzy' in message.flags:
            message.flags.remove('fuzzy')
            message._translations = None

        if len(message.flags) > 0:
            flags_comment = u", "+u", ".join(message.flags)
        else:
            flags_comment = u""

        potmsgset = self.getOrCreatePOTMsgSet(message)
        potmsgset.setSequence(self.potemplate, self.count)
        potmsgset.commenttext = message.comment
        potmsgset.sourcecomment = message.source_comment
        potmsgset.filereferences = message.file_references
        potmsgset.flagscomment = flags_comment

        translation_message = self.storeTranslationsInDatabase(
                                  message, potmsgset)

        # Update translation_message's comments and flags.
        if translation_message is not None:
            translation_message.comment = message.comment
            if self.translation_import_queue_entry.from_upstream:
                translation_message.was_obsolete_in_last_import = (
                    message.is_obsolete)


class POFileImporter(FileImporter):
    """Import a translation file."""

    def __init__(self, translation_import_queue_entry, importer, logger):
        """Construct an Importer for a translation file."""

        assert(translation_import_queue_entry.pofile is not None,
            "Pofile must not be None when importing a translation.")

        # Call base constructor
        super(POFileImporter, self).__init__(
             translation_import_queue_entry, importer, logger)

        self.pofile = translation_import_queue_entry.pofile
        self.potemplate = self.pofile.potemplate

        upload_header = self.translation_file.header
        if upload_header is not None:
            # Check whether we are importing a new version.
            if self.pofile.isTranslationRevisionDateOlder(upload_header):
                if translation_import_queue_entry.from_upstream:
                    # Upstream files can be older than the last import
                    # and still be imported. They don't update header
                    # information, though, so this is deleted here.
                    self.translation_file.header = None
                else:
                    # The new imported file is older than latest one imported,
                    # we don't import it, just ignore it as it could be a
                    # mistake and it would make us lose translations.
                    pofile_timestamp = (
                        self.pofile.getHeader().translation_revision_date)
                    upload_timestamp = (
                        upload_header.translation_revision_date)
                    raise OutdatedTranslationError(
                        'The last imported version of this file was '
                        'dated %s; the timestamp in the file you uploaded '
                        'is %s.' % (pofile_timestamp, upload_timestamp))
            # Get the timestamp when this file was exported from
            # Launchpad. If it was not exported from Launchpad, it will be
            # None.
            self.lock_timestamp = (
                upload_header.launchpad_export_date)

        if (not self.translation_import_queue_entry.from_upstream and
            self.lock_timestamp is None):
            # We got a translation file from offline translation (not from
            # upstream) and it misses the export time so we don't have a
            # way to figure whether someone changed the same translations
            # while the offline work was done.
            raise NotExportedFromLaunchpad

        # Update the header with the new one. If this is an old upstream
        # file, the new header has been set to None and no update will occur.
        self.pofile.updateHeader(self.translation_file.header)

        # Get last translator that touched this translation file.
        # We may not be able to guess it from the translation file, so
        # we take the importer as the last translator then.
        if upload_header is not None:
            name, email = upload_header.getLastTranslator()
            self.last_translator = self._getPersonByEmail(email, name)
        if self.last_translator is None:
            self.last_translator = (
                self.translation_import_queue_entry.importer)

        if self.translation_import_queue_entry.from_upstream:
            # An unprivileged user wouldn't have been able to upload an
            # upstream file in the first place.  But for Soyuz uploads,
            # the "importer" reflects the package upload, not the
            # translations upload.  So don't check for editing rights.
            self.is_editor = True
        else:
            # Use the importer rights to make sure the imported
            # translations are actually accepted instead of being just
            # suggestions.
            self.is_editor = (
                self.pofile.canEditTranslations(
                    self.translation_import_queue_entry.importer))

        from_upstream = self.translation_import_queue_entry.from_upstream
        self.pofile_in_db = ExistingPOFileInDatabase(
            self.pofile, is_current_upstream=from_upstream)

    def _getPersonByEmail(self, email, name=None):
        """Return the person for given email.

        If the person is unknown in Launchpad, the account will be created but
        it will not have a password and thus, will be disabled.

        :param email: text that contains the email address.
        :param name: name of the owner of the given email address.

        :return: A person object or None, if email is None.
        """
        if email is None:
            return None

        personset = getUtility(IPersonSet)

        # We may have to create a new person.  If we do, this is the
        # rationale.
        comment = 'when importing the %s translation of %s' % (
            self.pofile.language.displayname, self.potemplate.displayname)
        rationale = PersonCreationRationale.POFILEIMPORT

        try:
            return personset.ensurePerson(
                email, displayname=name, rationale=rationale, comment=comment)
        except InvalidEmailAddress:
            return None

    def importMessage(self, message):
        """See FileImporter."""
        # Mark this message as seen in the import
        self.pofile_in_db.markMessageAsSeen(message)
        if self.translation_import_queue_entry.from_upstream:
            if self.pofile_in_db.isAlreadyTranslatedTheSameUpstream(message):
                return
        else:
            if self.pofile_in_db.isAlreadyTranslatedTheSameInUbuntu(message):
                return

        potmsgset = self.getOrCreatePOTMsgSet(message)
        if potmsgset.getSequence(self.potemplate) == 0:
            # We are importing a message that does not exist in
            # latest translation template so we can update its values.
            potmsgset.sourcecomment = message.source_comment
            potmsgset.filereferences = message.file_references

        if 'fuzzy' in message.flags:
            message.flags.remove('fuzzy')
            message._translations = None

        translation_message = self.storeTranslationsInDatabase(
            message, potmsgset)

        # Update translation_message's comments and flags.
        if translation_message is not None:
            translation_message.comment = message.comment
            if self.translation_import_queue_entry.from_upstream:
                translation_message.was_obsolete_in_last_import = (
                    message.is_obsolete)

    def finishImport(self):
        """ Mark messages that were not imported. """
        # Get relevant messages from DB.
        unseen = self.pofile_in_db.getUnseenMessages()
        for unseen_message in unseen:
            (msgid, plural, context) = unseen_message
            potmsgset = self.potemplate.getPOTMsgSetByMsgIDText(
                msgid, plural_text=plural, context=context)
            if potmsgset is not None:
                previous_upstream_message = (
                    potmsgset.getImportedTranslationMessage(
                    self.potemplate, self.pofile.language,
                    self.pofile.variant))
                if previous_upstream_message is not None:
                    # The message was not imported this time, it
                    # therefore looses its imported status.
                    previous_upstream_message.is_current_upstream = False
