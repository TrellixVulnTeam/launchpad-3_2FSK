# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['POFile', 'DummyPOFile', 'POFileSet']

import StringIO
import pytz
import datetime
import os.path

# Zope interfaces
from zope.interface import implements, providedBy
from zope.component import getUtility
from zope.event import notify

from sqlobject import (
    ForeignKey, IntCol, StringCol, BoolCol, SQLObjectNotFound)

from canonical.database.sqlbase import (
    SQLBase, flush_database_updates, sqlvalues)
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.constants import UTC_NOW

from canonical.lp.dbschema import (
    EnumCol, RosettaImportStatus, TranslationPermission,
    TranslationValidationStatus)

import canonical.launchpad
from canonical.launchpad import helpers
from canonical.launchpad.mail import simple_sendmail
from canonical.launchpad.interfaces import (
    IPOFileSet, IPOFile, IRawFileData, IPOTemplateExporter,
    ZeroLengthPOExportError, ILibraryFileAliasSet, ILaunchpadCelebrities,
    NotFoundError, RawFileBusy)

from canonical.launchpad.database.pomsgid import POMsgID
from canonical.launchpad.database.potmsgset import POTMsgSet
from canonical.launchpad.database.pomsgset import POMsgSet, DummyPOMsgSet

from canonical.launchpad.components.rosettastats import RosettaStats
from canonical.launchpad.components.poimport import import_po, OldPOImported
from canonical.launchpad.components.poexport import FilePOFileOutput
from canonical.launchpad.components.poparser import (
    POSyntaxError, POHeader, POInvalidInputError)
from canonical.launchpad.event.sqlobjectevent import SQLObjectModifiedEvent


def _check_translation_perms(permission, translators, person):
    """This is a utility function that will return True or False depending
    on whether the person is part of the right group of translators, and the
    permission on the relevant project or product.
    """

    if person is None:
        return False

    rosetta_experts = getUtility(ILaunchpadCelebrities).rosetta_expert

    if person.inTeam(rosetta_experts):
        # Rosetta experts can edit translations always.
        return True

    # now, let's determine if the person is part of a designated
    # translation team
    is_designated_translator = False
    # XXX sabdfl 25/05/05 this code could be improved when we have
    # implemented CrowdControl
    for translator in translators:
        if person.inTeam(translator):
            is_designated_translator = True
            break

    # have a look at the applicable permission policy
    if permission == TranslationPermission.OPEN:
        # if the translation policy is "open", then yes, anybody is an
        # editor of any translation
        return True
    elif permission == TranslationPermission.STRUCTURED:
        # in the case of a STRUCTURED permission, designated translators
        # can edit, unless there are no translators, in which case
        # anybody can translate
        if len(translators) > 0:
            # when there are designated translators, only they can edit
            if is_designated_translator is True:
                return True
        else:
            # since there are no translators, anyone can edit
            return True
    elif permission == TranslationPermission.CLOSED:
        # if the translation policy is "closed", then check if the person is
        # in the set of translators
        if is_designated_translator:
            return True
    else:
        raise NotImplementedError('Unknown permission %s' % permission.name)

    # ok, thats all we can check, and so we must assume the answer is no
    return False


class POFile(SQLBase, RosettaStats):
    implements(IPOFile, IRawFileData)

    _table = 'POFile'

    potemplate = ForeignKey(foreignKey='POTemplate',
                            dbName='potemplate',
                            notNull=True)
    language = ForeignKey(foreignKey='Language',
                          dbName='language',
                          notNull=True)
    description = StringCol(dbName='description',
                            notNull=False,
                            default=None)
    topcomment = StringCol(dbName='topcomment',
                           notNull=False,
                           default=None)
    header = StringCol(dbName='header',
                       notNull=False,
                       default=None)
    fuzzyheader = BoolCol(dbName='fuzzyheader',
                          notNull=True)
    lasttranslator = ForeignKey(foreignKey='Person',
                                dbName='lasttranslator',
                                notNull=False,
                                default=None)
    license = IntCol(dbName='license',
                     notNull=False,
                     default=None)
    currentcount = IntCol(dbName='currentcount',
                          notNull=True,
                          default=0)
    updatescount = IntCol(dbName='updatescount',
                          notNull=True,
                          default=0)
    rosettacount = IntCol(dbName='rosettacount',
                          notNull=True,
                          default=0)
    lastparsed = UtcDateTimeCol(dbName='lastparsed',
                                notNull=False,
                                default=None)
    owner = ForeignKey(foreignKey='Person',
                       dbName='owner',
                       notNull=True)
    pluralforms = IntCol(dbName='pluralforms',
                         notNull=True)
    variant = StringCol(dbName='variant',
                        notNull=False,
                        default=None)
    path = StringCol(dbName='path',
                     notNull=False,
                     default=None)
    exportfile = ForeignKey(foreignKey='LibraryFileAlias',
                            dbName='exportfile',
                            notNull=False,
                            default=None)
    exporttime = UtcDateTimeCol(dbName='exporttime',
                                notNull=False,
                                default=None)
    datecreated = UtcDateTimeCol(notNull=True,
        default=UTC_NOW)

    latestsubmission = ForeignKey(foreignKey='POSubmission',
        dbName='latestsubmission', notNull=False, default=None)

    from_sourcepackagename = ForeignKey(foreignKey='SourcePackageName',
        dbName='from_sourcepackagename', notNull=False, default=None)

    @property
    def title(self):
        """See IPOFile."""
        title = '%s translation of %s' % (
            self.language.displayname, self.potemplate.displayname)
        return title

    @property
    def translators(self):
        """See IPOFile."""
        translators = set()
        for group in self.potemplate.translationgroups:
            translator = group.query_translator(self.language)
            if translator is not None:
                translators.add(translator)
        return sorted(list(translators),
            key=lambda x: x.translator.name)

    @property
    def translationpermission(self):
        """See IPOFile."""
        return self.potemplate.translationpermission

    @property
    def contributors(self):
        """See IPOFile."""
        from canonical.launchpad.database.person import Person

        return Person.select("""
            POSubmission.person = Person.id AND
            POSubmission.pomsgset = POMsgSet.id AND
            POMsgSet.pofile = %d""" % self.id,
            clauseTables=('POSubmission', 'POMsgSet'),
            distinct=True)

    def canEditTranslations(self, person):
        """See IPOFile."""
        # If the person is None, then they cannot edit
        if person is None:
            return False

        # Rosetta experts and admins can always edit translations.
        admins = getUtility(ILaunchpadCelebrities).admin
        rosetta_experts = getUtility(ILaunchpadCelebrities).rosetta_expert
        if (person.inTeam(admins) or person.inTeam(rosetta_experts) or
            person.id == rosetta_experts.id):
            return True

        # The owner of the product is also able to edit translations.
        if self.potemplate.productseries is not None:
            product = self.potemplate.productseries.product
            if person.inTeam(product.owner):
                return True

        # check based on permissions
        translators = [t.translator for t in self.translators]
        perm_result = _check_translation_perms(
            self.translationpermission,
            translators,
            person)
        if perm_result is True:
            return True

        # Finally, check for the owner of the PO file
        return person.inTeam(self.owner)

    def currentMessageSets(self):
        return POMsgSet.select(
            'POMsgSet.pofile = %d AND POMsgSet.sequence > 0' % self.id,
            orderBy='sequence')

    # XXX: Carlos Perello Marin 15/10/04: I don't think this method is needed,
    # it makes no sense to have such information or perhaps we should have it
    # as pot's len + the obsolete msgsets from this .po file.
    def __len__(self):
        """See IPOFile."""
        return self.translatedCount()

    def translated(self):
        """See IPOFile."""
        return iter(POMsgSet.select('''
            POMsgSet.pofile = %d AND
            POMsgSet.iscomplete=TRUE AND
            POMsgSet.potmsgset = POTMsgSet.id AND
            POTMsgSet.sequence > 0''' % self.id,
            clauseTables = ['POMsgSet']
            ))

    def untranslated(self):
        """See IPOFile."""
        raise NotImplementedError

    def __iter__(self):
        """See IPOFile."""
        return iter(self.currentMessageSets())

    def getPOMsgSet(self, msgid_text, onlyCurrent=False):
        """See IPOFile."""
        query = 'potemplate = %d' % self.potemplate.id
        if onlyCurrent:
            query += ' AND sequence > 0'

        if not isinstance(msgid_text, unicode):
            raise AssertionError(
                "Can't index with type %s. (Must be unicode.)" %
                    type(msgid_text))

        # Find a message ID with the given text.
        try:
            pomsgid = POMsgID.byMsgid(msgid_text)
        except SQLObjectNotFound:
            return None

        # Find a message set with the given message ID.

        potmsgset = POTMsgSet.selectOne(query +
            (' AND primemsgid = %d' % pomsgid.id))

        if potmsgset is None:
            return None

        pomsgset = POMsgSet.selectOneBy(
            potmsgsetID=potmsgset.id, pofileID=self.id)
        if pomsgset is None:
            # There isn't a POMsgSet yet, we return a Dummy one until we get a
            # write operation that creates the real one.
            return DummyPOMsgSet(self, potmsgset)
        else:
            return pomsgset

    def __getitem__(self, msgid_text):
        """See IPOFile."""
        pomsgset = self.getPOMsgSet(msgid_text)
        if pomsgset is None:
            raise NotFoundError(msgid_text)
        else:
            return pomsgset

    def getPOMsgSetsNotInTemplate(self):
        """See IPOFile."""
        return iter(POMsgSet.select('''
            POMsgSet.pofile = %d AND
            POMsgSet.potmsgset = POTMsgSet.id AND
            POMsgSet.sequence <> 0 AND
            POTMsgSet.sequence = 0''' % self.id,
            orderBy='sequence',
            clauseTables = ['POTMsgSet']))

    def getPOTMsgSetTranslated(self, slice=None):
        """See IPOFile."""
        # A POT set is translated only if the PO message set has
        # POMsgSet.iscomplete = TRUE.
        results = POTMsgSet.select('''
            POTMsgSet.potemplate = %s AND
            POTMsgSet.sequence > 0 AND
            POMsgSet.potmsgset = POTMsgSet.id AND
            POMsgSet.pofile = %s AND
            POMsgSet.isfuzzy = FALSE AND
            POMsgSet.iscomplete = TRUE
            ''' % sqlvalues(self.potemplate.id, self.id),
            clauseTables=['POMsgSet'],
            orderBy='POTMsgSet.sequence')

        if slice is not None:
            results = results[slice]

        for potmsgset in results:
            yield potmsgset

    def getPOTMsgSetFuzzy(self, slice=None):
        """See IPOFile."""
        results = POTMsgSet.select('''
            POTMsgSet.potemplate = %s AND
            POTMsgSet.sequence > 0 AND
            POMsgSet.potmsgset = POTMsgSet.id AND
            POMsgSet.pofile = %s AND
            POMsgSet.isfuzzy = TRUE
            ''' % sqlvalues(self.potemplate.id, self.id),
            clauseTables=['POMsgSet'],
            orderBy='POTmsgSet.sequence')

        if slice is not None:
            results = results[slice]

        for potmsgset in results:
            yield potmsgset

    def getPOTMsgSetUntranslated(self, slice=None):
        """See IPOFile."""
        # A POT set is not translated if the PO message set have
        # POMsgSet.iscomplete = FALSE or we don't have such POMsgSet or
        # POMsgSet.isfuzzy = TRUE.
        #
        # We are using raw queries because the LEFT JOIN.
        potmsgids = self._connection.queryAll('''
            SELECT POTMsgSet.id, POTMsgSet.sequence
            FROM POTMsgSet
            LEFT OUTER JOIN POMsgSet ON
                POTMsgSet.id = POMsgSet.potmsgset AND
                POMsgSet.pofile = %s
            WHERE
                (POMsgSet.isfuzzy = TRUE OR
                 POMsgSet.iscomplete = FALSE OR
                 POMsgSet.id IS NULL) AND
                 POTMsgSet.sequence > 0 AND
                 POTMsgSet.potemplate = %s
            ORDER BY POTMsgSet.sequence
            ''' % sqlvalues(self.id, self.potemplate.id))

        if slice is not None:
            # Want only a subset specified by slice.
            potmsgids = potmsgids[slice]

        ids = [str(L[0]) for L in potmsgids]

        if len(ids) > 0:
            # Get all POTMsgSet requested by the function using the ids that
            # we know are not 100% translated.
            # NOTE: This implementation put a hard limit on len(ids) == 9000
            # if we get more elements there we will get an exception. It
            # should not be a problem with our current usage of this method.
            results = POTMsgSet.select(
                'POTMsgSet.id IN (%s)' % ', '.join(ids),
            orderBy='POTMsgSet.sequence')

            for potmsgset in results:
                yield potmsgset

    def getPOTMsgSetWithErrors(self, slice=None):
        """See IPOFile."""
        results = POTMsgSet.select('''
            POTMsgSet.potemplate = %s AND
            POTMsgSet.sequence > 0 AND
            POMsgSet.potmsgset = POTMsgSet.id AND
            POMsgSet.pofile = %s AND
            POSelection.pomsgset = POMsgSet.id AND
            POSelection.publishedsubmission = POSubmission.id AND
            POSubmission.pluralform = 0 AND
            POSubmission.validationstatus <> %s
            ''' % sqlvalues(self.potemplate.id, self.id,
                            TranslationValidationStatus.OK),
            clauseTables=['POMsgSet', 'POSelection', 'POSubmission'],
            orderBy='POTmsgSet.sequence')

        if slice is not None:
            results = results[slice]

        for potmsgset in results:
            yield potmsgset

    def hasMessageID(self, messageID):
        """See IPOFile."""
        results = POMsgSet.select('''
            POMsgSet.pofile = %d AND
            POMsgSet.potmsgset = POTMsgSet.id AND
            POTMsgSet.primemsgid = %d''' % (self.id, messageID.id))
        return results.count() > 0

    def messageCount(self):
        """See IRosettaStats."""
        return self.potemplate.messageCount()

    def currentCount(self, language=None):
        """See IRosettaStats."""
        return self.currentcount

    def updatesCount(self, language=None):
        """See IRosettaStats."""
        return self.updatescount

    def rosettaCount(self, language=None):
        """See IRosettaStats."""
        return self.rosettacount

    @property
    def fuzzy_count(self):
        """See IPOFile."""
        return POMsgSet.select("""
            pofile = %s AND
            isfuzzy IS TRUE AND
            sequence > 0
            """ % sqlvalues(self.id)).count()

    def expireAllMessages(self):
        """See IPOFile."""
        for msgset in self.currentMessageSets():
            msgset.sequence = 0

    def updateStatistics(self, tested=False):
        """See IPOFile."""
        # make sure all the data is in the db
        flush_database_updates()
        # make a note of the pre-update position
        prior_current = self.currentcount
        prior_updates = self.updatescount
        prior_rosetta = self.rosettacount
        current = POMsgSet.select('''
            POMsgSet.pofile = %d AND
            POMsgSet.sequence > 0 AND
            POMsgSet.publishedfuzzy = FALSE AND
            POMsgSet.publishedcomplete = TRUE AND
            POMsgSet.potmsgset = POTMsgSet.id AND
            POTMsgSet.sequence > 0
            ''' % self.id, clauseTables=['POTMsgSet']).count()

        updates = POMsgSet.select('''
            POMsgSet.pofile = %s AND
            POMsgSet.sequence > 0 AND
            POMsgSet.isfuzzy = FALSE AND
            POMsgSet.iscomplete = TRUE AND
            POMsgSet.publishedfuzzy = FALSE AND
            POMsgSet.publishedcomplete = TRUE AND
            POMsgSet.isupdated = TRUE AND
            POMsgSet.potmsgset = POTMsgSet.id AND
            POTMsgSet.sequence > 0
            ''' % sqlvalues(self.id),
            clauseTables=['POTMsgSet']).count()

        if tested:
            updates_from_first_principles = POMsgSet.select('''
                POMsgSet.pofile = %s AND
                POMsgSet.sequence > 0 AND
                POMsgSet.isfuzzy = FALSE AND
                POMsgSet.iscomplete = TRUE AND
                POMsgSet.publishedfuzzy = FALSE AND
                POMsgSet.publishedcomplete = TRUE AND
                POMsgSet.potmsgset = POTMsgSet.id AND
                POTMsgSet.sequence > 0 AND
                ActiveSubmission.id = POSelection.activesubmission AND
                PublishedSubmission.id = POSelection.publishedsubmission AND
                POSelection.pomsgset = POMsgSet.id AND
                ActiveSubmission.datecreated > PublishedSubmission.datecreated
                ''' % sqlvalues(self.id),
                clauseTables=['POSelection',
                              'POTMsgSet',
                              'POSubmission AS ActiveSubmission',
                              'POSubmission AS PublishedSubmission']).count()
            if updates != updates_from_first_principles:
                raise AssertionError('Failure in update statistics.')

        rosetta = POMsgSet.select('''
            POMsgSet.pofile = %d AND
            POMsgSet.isfuzzy = FALSE AND
            POMsgSet.iscomplete = TRUE AND
            ( POMsgSet.sequence < 1 OR
              POMsgSet.publishedcomplete = FALSE OR
              POMsgSet.publishedfuzzy=TRUE ) AND
            POMsgSet.potmsgset = POTMsgSet.id AND
            POTMsgSet.sequence > 0
            ''' % self.id,
            clauseTables=['POTMsgSet']).count()
        self.currentcount = current
        self.updatescount = updates
        self.rosettacount = rosetta
        return (current, updates, rosetta)

    def createMessageSetFromMessageSet(self, potmsgset):
        """See IPOFile."""
        pomsgset = POMsgSet(
            sequence=0,
            pofile=self,
            iscomplete=False,
            publishedcomplete=False,
            obsolete=False,
            isfuzzy=False,
            publishedfuzzy=False,
            potmsgset=potmsgset)
        return pomsgset

    def createMessageSetFromText(self, text):
        """See IPOFile."""
        try:
            potmsgset = self.potemplate[text]
        except KeyError:
            potmsgset = self.potemplate.createMessageSetFromText(text)

        return self.createMessageSetFromMessageSet(potmsgset)

    def updateHeader(self, new_header):
        """See IPOFile."""
        # check that the plural forms info is valid
        new_plural_form = new_header.get('Plural-Forms', None)
        if new_plural_form is None:
            # The new header does not have plural form information.
            # Parse the old header.
            old_header = POHeader(msgstr=self.header)
            # The POHeader needs to know is ready to be used.
            old_header.updateDict()
            old_plural_form = old_header.get('Plural-Forms', None)
            if old_plural_form is not None:
                # First attempt: use the plural-forms header that is already
                # in the database, if it exists.
                new_header['Plural-Forms'] = old_header['Plural-Forms']
            elif self.language.pluralforms is not None:
                # Second attempt: get the default value for plural-forms from
                # the language table.
                new_header['Plural-Forms'] = self.language.pluralforms
            else:
                # we absolutely don't know it; only complain if
                # a plural translation is present
                # XXX Carlos Perello Marin 2005-06-15: We should implement:
                # https://launchpad.ubuntu.com/malone/bugs/1186 instead of
                # set it to this default value...
                new_header['Plural-Forms'] = 1
        # XXX sabdfl 27/05/05 should we also differentiate between
        # washeaderfuzzy and isheaderfuzzy?
        self.topcomment = new_header.commentText
        self.header = new_header.msgstr
        self.fuzzyheader = 'fuzzy' in new_header.flags
        self.pluralforms = new_header.nplurals

    def isPORevisionDateOlder(self, header):
        """See IPOFile."""
        old_header = POHeader(msgstr=self.header)
        old_header.updateDict()

        # Get the old and new PO-Revision-Date entries as datetime objects.
        # That's the second element from the tuple that getPORevisionDate
        # returns.
        (old_date_string, old_date) = old_header.getPORevisionDate()
        (new_date_string, new_date) = header.getPORevisionDate()

        # Check whether or not the date is older.
        if old_date is None or new_date is None or old_date <= new_date:
            # If one of the headers, or both headers, has a missing or wrong
            # PO-Revision-Date, then they cannot be compared, so we consider
            # the new header to be the most recent.
            return False
        elif old_date > new_date:
            return True

    # ICanAttachRawFileData implementation
    def attachRawFileData(self, contents, published, importer=None,
        date_imported=UTC_NOW):
        """See ICanAttachRawFileData."""
        rawfile = IRawFileData(self)

        if rawfile.rawimportstatus == RosettaImportStatus.PENDING:
            raise RawFileBusy

        if self.variant:
            filename = '%s@%s.po' % (
                self.language.code, self.variant.encode('utf8'))
        else:
            filename = '%s.po' % self.language.code

        helpers.attachRawFileData(
            self, filename, contents, importer, date_imported)

        rawfile.rawfilepublished = published

    def attachRawFileDataAsFileAlias(self, alias, published, importer=None,
        date_imported=UTC_NOW):
        """See ICanAttachRawFileData."""
        rawfile = IRawFileData(self)

        if rawfile.rawimportstatus == RosettaImportStatus.PENDING:
            raise RawFileBusy

        helpers.attachRawFileDataByFileAlias(
            self, alias, importer, date_imported)

        rawfile.rawfilepublished = published

    # IRawFileData implementation

    # Any use of this interface should adapt this object as an IRawFileData.

    rawfile = ForeignKey(foreignKey='LibraryFileAlias', dbName='rawfile',
                         notNull=False, default=None)
    rawimporter = ForeignKey(foreignKey='Person', dbName='rawimporter',
                             notNull=False, default=None)
    daterawimport = UtcDateTimeCol(dbName='daterawimport', notNull=False,
                                   default=None)
    rawimportstatus = EnumCol(dbName='rawimportstatus', notNull=True,
        schema=RosettaImportStatus, default=RosettaImportStatus.IGNORE)

    rawfilepublished = BoolCol(notNull=False, default=None)

    def doRawImport(self, logger=None):
        """See IRawFileData."""
        rawdata = helpers.getRawFileData(self)

        file = StringIO.StringIO(rawdata)

        # Store the object status before the changes.
        object_before_modification = helpers.Snapshot(
            self, providing=providedBy(self))

        try:
            errors = import_po(self, file, self.rawfilepublished)
        except (POSyntaxError, POInvalidInputError):
            # The import failed, we mark it as failed so we could review it
            # later in case it's a bug in our code.
            # XXX Carlos Perello Marin 2005-06-22: We should intregrate this
            # kind of error with the new TranslationValidation feature.
            self.rawimportstatus = RosettaImportStatus.FAILED
            if logger:
                logger.warning(
                    'Error importing %s' % self.title, exc_info=1)
            return
        except OldPOImported:
            # The attached file is older than the last imported one, we ignore
            # it.
            self.rawimportstatus = RosettaImportStatus.IGNORE
            if logger:
                logger.warning('Got an old version for %s' % self.title)
            return

        # Request a sync of 'self' as we need to use real datetime values.
        self.sync()

        # Prepare the mail notification.

        msgsets_imported = POMsgSet.select(
            'sequence > 0 AND pofile=%s' % (sqlvalues(self.id))).count()

        UTC = pytz.timezone('UTC')
        # XXX: Carlos Perello Marin 2005-06-29 This code should be using the
        # solution defined by PresentingLengthsOfTime spec when it's
        # implemented.
        elapsedtime = datetime.datetime.now(UTC) - self.daterawimport
        elapsedtime_text = ''
        hours = elapsedtime.seconds / 3600
        minutes = (elapsedtime.seconds % 3600) / 60
        if elapsedtime.days > 0:
            elapsedtime_text += '%d days ' % elapsedtime.days
        if hours > 0:
            elapsedtime_text += '%d hours ' % hours
        if minutes > 0:
            elapsedtime_text += '%d minutes ' % minutes

        if len(elapsedtime_text) > 0:
            elapsedtime_text += 'ago'
        else:
            elapsedtime_text = 'just requested'

        replacements = {
            'importer': self.rawimporter.displayname,
            'dateimport': self.daterawimport.strftime('%F %R%z'),
            'elapsedtime': elapsedtime_text,
            'numberofmessages': msgsets_imported,
            'language': self.language.displayname,
            'template': self.potemplate.displayname
            }

        if len(errors):
            # There were errors.
            errorsdetails = ''
            for error in errors:
                pomsgset = error['pomsgset']
                pomessage = error['pomessage']
                error_message = error['error-message']
                errorsdetails = errorsdetails + '%d.  [msg %d]\n"%s":\n\n%s\n\n' % (
                    pomsgset.potmsgset.sequence,
                    pomsgset.sequence,
                    error_message,
                    unicode(pomessage))

            replacements['numberoferrors'] = len(errors)
            replacements['errorsdetails'] = errorsdetails
            replacements['numberofcorrectmessages'] = (msgsets_imported -
                len(errors))

            template_mail = 'poimport-error.txt'
            subject = 'Translation problems - %s - %s' % (
                self.language.displayname, self.potemplate.displayname)
        else:
            template_mail = 'poimport-confirmation.txt'
            subject = 'Translation import - %s - %s' % (
                self.language.displayname, self.potemplate.displayname)

        # Send the email.
        template_file = os.path.join(
            os.path.dirname(canonical.launchpad.__file__),
            'emailtemplates', template_mail)
        template = open(template_file).read()
        message = template % replacements

        fromaddress = 'Rosetta SWAT Team <rosetta@ubuntu.com>'
        toaddress = helpers.contactEmailAddresses(self.rawimporter)

        simple_sendmail(fromaddress, toaddress, subject, message)

        # The import has been done, we mark it that way.
        self.rawimportstatus = RosettaImportStatus.IMPORTED

        # Now we update the statistics after this new import
        self.updateStatistics()

        # List of fields that would be updated.
        fields = ['header', 'topcomment', 'fuzzyheader', 'pluralforms',
                  'rawimportstatus', 'currentcount', 'updatescount',
                  'rosettacount']

        # And finally, emit the modified event.
        notify(SQLObjectModifiedEvent(self, object_before_modification, fields))

    def validExportCache(self):
        """See IPOFile."""
        if self.exportfile is None:
            return False

        if self.latestsubmission is None:
            return True

        change_time = self.latestsubmission.datecreated
        return change_time < self.exporttime

    def updateExportCache(self, contents):
        """See IPOFile."""
        alias_set = getUtility(ILibraryFileAliasSet)

        if self.variant:
            filename = '%s@%s.po' % (
                self.language.code, self.variant.encode('UTF-8'))
        else:
            filename = '%s.po' % (self.language.code)

        size = len(contents)
        file = StringIO.StringIO(contents)

        # Note that UTC_NOW is resolved to the time at the beginning of the
        # transaction. This is significant because translations could be added
        # to the database while the export transaction is in progress, and the
        # export would not include those translations. However, we want to be
        # able to compare the export time to other datetime object within the
        # same transaction -- e.g. in a call to validExportCache(). This is
        # why we call .sync() -- it turns the UTC_NOW reference into an
        # equivalent datetime object.

        self.exportfile = alias_set.create(
            filename, size, file, 'appliction/x-po')
        self.exporttime = UTC_NOW
        self.sync()

    def fetchExportCache(self):
        """Return the cached export file, if it exists, or None otherwise."""

        if self.exportfile is None:
            return None
        else:
            alias_set = getUtility(ILibraryFileAliasSet)
            return alias_set[self.exportfile.id].read()

    def uncachedExport(self, included_obsolete=True):
        """See IPOFile."""
        exporter = IPOTemplateExporter(self.potemplate)
        return exporter.export_pofile(self.language, self.variant,
            included_obsolete)

    def export(self, included_obsolete=True):
        """See IPOFile."""
        if self.validExportCache() and included_obsolete:
            # Only use the cache if the request includes obsolete messages,
            # without them, we always do a full export.
            return self.fetchExportCache()
        else:
            contents = self.uncachedExport()

            if len(contents) == 0:
                raise ZeroLengthPOExportError

            if included_obsolete:
                # Update the cache if the request includes obsolete messages.
                self.updateExportCache(contents)
            return contents

    def exportToFileHandle(self, filehandle, included_obsolete=True):
        """See IPOFile."""
        exporter = IPOTemplateExporter(self.potemplate)
        exporter.export_pofile_to_file(filehandle, self.language,
            self.variant, included_obsolete)

    def invalidateCache(self):
        """See IPOFile."""
        self.exportfile = None


class DummyPOFile(RosettaStats):
    """Represents a POFile where we do not yet actually HAVE a POFile for
    that language for this template.
    """
    implements(IPOFile)

    def __init__(self, potemplate, language, owner=None,
        header='Content-Type: text/plain; charset=us-ascii'):
        self.potemplate = potemplate
        self.language = language
        self.owner = owner
        self.header = header
        self.latestsubmission = None
        self.pluralforms = language.pluralforms
        self.translationpermission = self.potemplate.translationpermission
        self.lasttranslator = None
        self.contributors = []

    def messageCount(self):
        return len(self.potemplate)

    @property
    def title(self):
        """See IPOFile."""
        title = '%s translation of %s' % (
            self.language.displayname, self.potemplate.displayname)
        return title

    @property
    def translators(self):
        tgroups = self.potemplate.translationgroups
        ret = []
        for group in tgroups:
            translator = group.query_translator(self.language)
            if translator is not None:
                ret.append(translator)
        return ret

    def canEditTranslations(self, person):
        """See IPOFile."""
        # If the person is None, then they cannot edit
        if person is None:
            return False

        # Rosetta experts and admins can always edit translations.
        admins = getUtility(ILaunchpadCelebrities).admin
        rosetta_experts = getUtility(ILaunchpadCelebrities).rosetta_expert
        if person.inTeam(admins) or person.inTeam(rosetta_experts):
            return True

        # The owner of the product is also able to edit translations.
        if self.potemplate.productseries is not None:
            product = self.potemplate.productseries.product
            if person.inTeam(product.owner):
                return True

        translators = [t.translator for t in self.translators]
        return _check_translation_perms(
            self.translationpermission,
            translators,
            person)

    def currentCount(self):
        return 0

    def rosettaCount(self):
        return 0

    def updatesCount(self):
        return 0

    def nonUpdatesCount(self):
        return 0

    def translatedCount(self):
        return 0

    def untranslatedCount(self):
        return self.messageCount()

    def currentPercentage(self):
        return 0.0

    def rosettaPercentage(self):
        return 0.0

    def updatesPercentage(self):
        return 0.0

    def nonUpdatesPercentage(self):
        return 0.0

    def translatedPercentage(self):
        return 0.0

    def untranslatedPercentage(self):
        return 100.0


class POFileSet:
    implements(IPOFileSet)

    def getPOFilesPendingImport(self):
        """See IPOFileSet."""
        results = POFile.selectBy(
            rawimportstatus=RosettaImportStatus.PENDING,
            orderBy='-daterawimport')

        for pofile in results:
            yield pofile

    def getDummy(self, potemplate, language):
        return DummyPOFile(potemplate, language)

    def getPOFileByPathAndOrigin(self, path, productseries=None,
        distrorelease=None, sourcepackagename=None):
        """See IPOFileSet."""
        if productseries is not None:
            return POFile.selectOne('''
                POFile.path = %s AND
                POFile.potemplate = POTemplate.id AND
                POTemplate.productseries = %s''' % sqlvalues(
                    path, productseries.id),
                clauseTables=['POTemplate'])
        elif sourcepackagename is not None:
            # The POTemplate belongs to a distribution and it could come from
            # another package that the one it's linked to, so we first check
            # to find it at IPOTemplate.from_sourcepackagename
            pofile = POFile.selectOne('''
                POFile.path = %s AND
                POFile.potemplate = POTemplate.id AND
                POTemplate.distrorelease = %s AND
                POTemplate.from_sourcepackagename = %s''' % sqlvalues(
                    path, distrorelease.id, sourcepackagename.id),
                clauseTables=['POTemplate'])

            if pofile is not None:
                return pofile

            # There is no pofile in that 'path' and
            # 'from_sourcepackagename' so we do a search using the usual
            # sourcepackagename.
            return POFile.selectOne('''
                POFile.path = %s AND
                POFile.potemplate = POTemplate.id AND
                POTemplate.distrorelease = %s AND
                POTemplate.sourcepackagename = %s''' % sqlvalues(
                    path, distrorelease.id, sourcepackagename.id),
                clauseTables=['POTemplate'])
        else:
            raise AssertionError(
                'Either productseries or sourcepackagename arguments must be'
                ' not None.')
