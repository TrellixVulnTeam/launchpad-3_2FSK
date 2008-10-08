# Copyright 2004-2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = ['POTMsgSet']

import gettextpo

from zope.interface import implements
from zope.component import getUtility

from sqlobject import ForeignKey, IntCol, StringCol, SQLObjectNotFound

from canonical.database.constants import DEFAULT, UTC_NOW
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.launchpad import helpers
from canonical.launchpad.interfaces import (
    BrokenTextError, ILaunchpadCelebrities, IPOTMsgSet,
    RosettaTranslationOrigin, TranslationConflict, TranslationConstants,
    TranslationValidationStatus)
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.interfaces.pofile import IPOFileSet
from canonical.launchpad.database.pomsgid import POMsgID
from canonical.launchpad.database.potranslation import POTranslation
from canonical.launchpad.database.translationmessage import (
    DummyTranslationMessage, TranslationMessage)
from canonical.launchpad.database.translationtemplateitem import (
    TranslationTemplateItem)


# Msgids that indicate translation credit messages, and their
# contexts.
credit_message_ids = {
    # Regular gettext credits messages.
    u'translation-credits': None,
    u'translator-credits': None,
    u'translator_credits': None,

    # KDE credits messages.
    u'Your emails': u'EMAIL OF TRANSLATORS',
    u'Your names': u'NAME OF TRANSLATORS',

    # Old KDE credits messages.
    u'_: EMAIL OF TRANSLATORS\nYour emails': None,
    u'_: NAME OF TRANSLATORS\nYour names': None,
    }


class POTMsgSet(SQLBase):
    implements(IPOTMsgSet)

    _table = 'POTMsgSet'

    context = StringCol(dbName='context', notNull=False)
    msgid_singular = ForeignKey(foreignKey='POMsgID', dbName='msgid_singular',
        notNull=True)
    msgid_plural = ForeignKey(foreignKey='POMsgID', dbName='msgid_plural',
        notNull=False, default=DEFAULT)
    sequence = IntCol(dbName='sequence', notNull=True)
    potemplate = ForeignKey(foreignKey='POTemplate', dbName='potemplate',
        notNull=True)
    commenttext = StringCol(dbName='commenttext', notNull=False)
    filereferences = StringCol(dbName='filereferences', notNull=False)
    sourcecomment = StringCol(dbName='sourcecomment', notNull=False)
    flagscomment = StringCol(dbName='flagscomment', notNull=False)

    _cached_singular_text = None

    def __storm_invalidated__(self):
        self._cached_singular_text = None

    @property
    def singular_text(self):
        """See `IPOTMsgSet`."""
        if self._cached_singular_text is not None:
            return self._cached_singular_text

        if self.potemplate.uses_english_msgids:
            self._cached_singular_text = self.msgid_singular.msgid
            return self._cached_singular_text

        # Singular text is stored as an "English translation."
        translation_message = self.getCurrentTranslationMessage(
            getUtility(ILaunchpadCelebrities).english)
        if translation_message is not None:
            msgstr0 = translation_message.msgstr0
            if msgstr0 is not None:
                self._cached_singular_text = msgstr0.translation
                return self._cached_singular_text

        # There is no "English translation," at least not yet.  Return
        # symbolic msgid, but do not cache--an English text may still be
        # imported.
        return self.msgid_singular.msgid

    def clearCachedSingularText(self):
        """Clear cached result for `singular_text`, if any."""
        self._cached_singular_text = None

    @property
    def plural_text(self):
        """See `IPOTMsgSet`."""
        if self.msgid_plural is None:
            return None
        else:
            return self.msgid_plural.msgid

    def getCurrentDummyTranslationMessage(self, language):
        """See `IPOTMsgSet`."""
        assert self.getCurrentTranslationMessage(language) is None, (
            'There is already a translation message in our database.')

        pofile = self.potemplate.getPOFileByLang(language.code)
        if pofile is None:
            pofileset = getUtility(IPOFileSet)
            pofile = pofileset.getDummy(self.potemplate, language)
        return DummyTranslationMessage(pofile, self)

    def getCurrentTranslationMessage(self, language, variant=None):
        """See `IPOTMsgSet`."""
        # Change 'is_current IS TRUE' condition carefully: it
        # needs to match condition specified in indexes, or Postgres
        # may not pick them up (in complicated queries, Postgres query
        # optimizer sometimes does text-matching of indexes).
        clauses = ['potmsgset = %s' % sqlvalues(self),
                   'is_current IS TRUE',
                   'POFile.language = %s' % sqlvalues(language),
                   'POFile.id = TranslationMessage.pofile']
        if variant is None:
            clauses.append('POFile.variant IS NULL')
        else:
            clauses.append('POFile.variant=%s' % sqlvalues(variant))
        return TranslationMessage.selectOne(' AND '.join(clauses),
                                            clauseTables=['POFile'])

    def getImportedTranslationMessage(self, language, variant=None):
        """See `IPOTMsgSet`."""
        # Change 'is_imported IS TRUE' condition carefully: it
        # needs to match condition specified in indexes, or Postgres
        # may not pick them up (in complicated queries, Postgres query
        # optimizer sometimes does text-matching of indexes).
        clauses = ['potmsgset = %s' % sqlvalues(self),
                   'is_imported IS TRUE',
                   'POFile.language = %s' % sqlvalues(language),
                   'POFile.id = TranslationMessage.pofile']
        if variant is None:
            clauses.append('POFile.variant IS NULL')
        else:
            clauses.append('POFile.variant=%s' % sqlvalues(variant))
        return TranslationMessage.selectOne(' AND '.join(clauses),
                                            clauseTables=['POFile'])

    def getLocalTranslationMessages(self, language):
        """See `IPOTMsgSet`."""
        query = """
            is_current IS NOT TRUE AND
            is_imported IS NOT TRUE AND
            potmsgset = %s AND
            POFile.language = %s AND
            pofile=POFile.id
            """ % sqlvalues(self, language)
        current = self.getCurrentTranslationMessage(language)
        if current is not None:
            if current.date_reviewed is None:
                comparing_date = current.date_created
            else:
                comparing_date = current.date_reviewed
            query += " AND date_created > %s" % sqlvalues(comparing_date)

        result = TranslationMessage.select(query, clauseTables=['POFile'])
        return shortlist(result, longest_expected=20, hardlimit=100)

    def _getExternalTranslationMessages(self, language, used):
        """Return external suggestions for this message.

        External suggestions are all TranslationMessages for the
        same english string which are used or suggested in other templates.

        A message is used if it's either imported or current, and unused
        otherwise.
        """
        # Return empty list (no suggestions) for translation credit strings
        # because they are automatically translated.
        if self.is_translation_credit:
            return []
        # Watch out when changing this condition: make sure it's done in
        # a way so that indexes are indeed hit when the query is executed.
        # Also note that there is a NOT(in_use_clause) index.
        in_use_clause = "(is_current IS TRUE OR is_imported IS TRUE)"
        if used:
            query = [in_use_clause]
        else:
            query = ["(NOT %s)" % in_use_clause]
        query.append('POFile.language = %s' % sqlvalues(language))
        query.append('POFile.id = TranslationMessage.pofile')

        query.append('''
            potmsgset IN (
                SELECT POTMsgSet.id
                FROM POTMsgSet
                JOIN POTemplate ON
                    POTMsgSet.potemplate = POTemplate.id
                LEFT JOIN ProductSeries ON
                    POTemplate.productseries = ProductSeries.id
                LEFT JOIN Product ON
                    ProductSeries.product = Product.id
                LEFT JOIN DistroSeries ON
                    POTemplate.distroseries = DistroSeries.id
                LEFT JOIN Distribution ON
                    DistroSeries.distribution = Distribution.id
                WHERE
                    POTMsgSet.id <> %s AND
                    msgid_singular = %s AND
                    POTemplate.iscurrent AND
                    (Product.official_rosetta OR Distribution.official_rosetta)
            )''' % sqlvalues(self, self.msgid_singular))

        # Subquery to find the ids of TranslationMessages that are
        # matching suggestions.
        # We're going to get a lot of duplicates, sometimes resulting in
        # thousands of suggstions.  Weed out most of that duplication by
        # excluding older messages that are identical to newer ones in
        # all translated forms.  The Python code can later sort out the
        # distinct translations per form.
        msgstrs = ', '.join([
            'COALESCE(msgstr%d, -1)' % form
            for form in xrange(TranslationConstants.MAX_PLURAL_FORMS)])
        ids_query_params = {
            'msgstrs': msgstrs,
            'where': ' AND '.join(query)
        }
        ids_query = '''
            SELECT DISTINCT ON (%(msgstrs)s)
                TranslationMessage.id
            FROM TranslationMessage
            JOIN POFile ON POFile.id = TranslationMessage.pofile
            WHERE %(where)s
            ORDER BY %(msgstrs)s, date_created DESC
            ''' % ids_query_params

        result = TranslationMessage.select('id IN (%s)' % ids_query)

        return shortlist(result, longest_expected=100, hardlimit=2000)

    def getExternallyUsedTranslationMessages(self, language):
        """See `IPOTMsgSet`."""
        return self._getExternalTranslationMessages(language, used=True)

    def getExternallySuggestedTranslationMessages(self, language):
        """See `IPOTMsgSet`."""
        return self._getExternalTranslationMessages(language, used=False)

    def flags(self):
        if self.flagscomment is None:
            return []
        else:
            return [flag
                    for flag in self.flagscomment.replace(' ', '').split(',')
                    if flag != '']

    def hasTranslationChangedInLaunchpad(self, language):
        """See `IPOTMsgSet`."""
        imported_translation = self.getImportedTranslationMessage(language)
        return (imported_translation is not None and
                not imported_translation.is_current)

    def isTranslationNewerThan(self, pofile, timestamp):
        """See `IPOTMsgSet`."""
        current = self.getCurrentTranslationMessage(pofile.language)
        if current is None:
            return False
        date_updated = current.date_created
        if (current.date_reviewed is not None and
            current.date_reviewed > date_updated):
            date_updated = current.date_reviewed
        return (date_updated is not None and date_updated > timestamp)

    def _list_of_msgids(self):
        """Return a list of [singular_text, plural_text] if the message
        is using plural forms, or just [singular_text] if it's not.
        """
        original_texts = [self.singular_text]
        if self.plural_text is not None:
            original_texts.append(self.plural_text)
        return original_texts

    def _sanitizeTranslations(self, translations, pluralforms):
        """Sanitize `translations` using self.applySanityFixes.

        If there is no certain pluralform in `translations`, set it to None.
        If there are `translations` with greater pluralforms than allowed,
        sanitize and keep them.
        """
        # Strip any trailing or leading whitespace, and normalize empty
        # translations to None.
        sanitized_translations = {}
        for pluralform in range(pluralforms):
            if pluralform < len(translations):
                sanitized_translations[pluralform] = self.applySanityFixes(
                    translations[pluralform])
            else:
                sanitized_translations[pluralform] = None
        # Unneeded plural forms are stored as well (needed since we may
        # have incorrect plural form data, so we can just reactivate them
        # once we fix the plural information for the language)
        for index, value in enumerate(translations):
            if index not in sanitized_translations:
                sanitized_translations[index] = self.applySanityFixes(value)

        return sanitized_translations

    def _validate_translations(self, translations, ignore_errors):
        """Validate all the `translations` and return a validation_status."""
        # By default all translations are correct.
        validation_status = TranslationValidationStatus.OK

        # Cache the list of singular_text and plural_text
        original_texts = self._list_of_msgids()

        # Validate the translation we got from the translation form
        # to know if gettext is unhappy with the input.
        try:
            helpers.validate_translation(
                original_texts, translations, self.flags())
        except gettextpo.error:
            if ignore_errors:
                # The translations are stored anyway, but we set them as
                # broken.
                validation_status = TranslationValidationStatus.UNKNOWNERROR
            else:
                # Check to know if there is any translation.
                has_translations = False
                for key in translations.keys():
                    if translations[key] is not None:
                        has_translations = True
                        break

                if has_translations:
                    # Partial translations cannot be stored, the
                    # exception is raised again and handled outside
                    # this method.
                    raise

        return validation_status

    def _findPOTranslations(self, translations):
        """Find all POTranslation records for passed `translations`."""
        potranslations = {}
        # Set all POTranslations we can have (up to MAX_PLURAL_FORMS)
        for pluralform in xrange(TranslationConstants.MAX_PLURAL_FORMS):
            if (pluralform in translations and
                translations[pluralform] is not None):
                translation = translations[pluralform]
                # Find or create a POTranslation for the specified text
                try:
                    potranslations[pluralform] = (
                        POTranslation.byTranslation(translation))
                except SQLObjectNotFound:
                    potranslations[pluralform] = (
                        POTranslation(translation=translation))
            else:
                potranslations[pluralform] = None
        return potranslations

    def _findTranslationMessage(self, pofile, potranslations, pluralforms):
        """Find a message for this `pofile` exactly matching given
        `translations` strings comparing only `pluralforms` of them.
        """
        clauses = ['potmsgset = %s' % sqlvalues(self),
                   'pofile = %s' % sqlvalues(pofile)]

        for pluralform in range(pluralforms):
            if potranslations[pluralform] is None:
                clauses.append('msgstr%s IS NULL' % sqlvalues(pluralform))
            else:
                clauses.append('msgstr%s=%s' % (
                    sqlvalues(pluralform, potranslations[pluralform])))
        return TranslationMessage.selectOne(' AND '.join(clauses))

    def _makeTranslationMessageCurrent(self, pofile, new_message, is_imported,
                                       submitter):
        """Make the given translation message the current one."""
        current_message = self.getCurrentTranslationMessage(pofile.language)
        if is_imported:
            # A new imported message is made current
            # only if there is no existing current message
            # or if the current message came from import
            # or if current message is empty (deactivated translation).
            # Empty imported translations should not replace
            # non-empty imported translations.
            if (current_message is None or
                (current_message.is_imported and
                 (current_message.is_empty or not new_message.is_empty)) or
                current_message.is_empty):
                new_message.is_current = True
                # Don't update the submitter and date changed
                # if there was no current message and an empty
                # message is submitted.
                if (not (current_message is None and
                         new_message.is_empty)):
                    pofile.lasttranslator = submitter
                    pofile.date_changed = UTC_NOW
        else:
            # Non-imported translations.
            new_message.is_current = True
            pofile.lasttranslator = submitter
            pofile.date_changed = UTC_NOW

            if new_message.origin == RosettaTranslationOrigin.ROSETTAWEB:
                # The submitted translation came from our UI, we give
                # give karma to the submitter of that translation.
                new_message.submitter.assignKarma(
                    'translationsuggestionapproved',
                    product=self.potemplate.product,
                    distribution=self.potemplate.distribution,
                    sourcepackagename=self.potemplate.sourcepackagename)

            # If the current message has been changed, and it was submitted
            # by a different person than is now doing the review (i.e.
            # `submitter`), then give this reviewer karma as well.
            if new_message != current_message:
                if new_message.submitter != submitter:
                    submitter.assignKarma(
                        'translationreview',
                        product=self.potemplate.product,
                        distribution=self.potemplate.distribution,
                        sourcepackagename=self.potemplate.sourcepackagename)

                new_message.reviewer = submitter
                new_message.date_reviewed = UTC_NOW
                pofile.date_changed = UTC_NOW
                pofile.lasttranslator = submitter

    def _isTranslationMessageASuggestion(self, force_suggestion,
                                         pofile, submitter,
                                         force_edition_rights, is_imported,
                                         lock_timestamp):
        # Whether a message should be saved as a suggestion and
        # whether a we should display a warning when an older translation is
        # submitted.
        # Returns a pair of (just_a_suggestion, warn_about_lock_timestamp).

        if force_suggestion:
            return True, False

        # Is the submitter allowed to edit translations?
        is_editor = (force_edition_rights or
                     pofile.canEditTranslations(submitter))

        assert (is_imported or is_editor or
                pofile.canAddSuggestions(submitter)), (
                  '%s cannot add translations nor can add suggestions' % (
                    submitter.displayname))

        if is_imported and not is_editor:
            raise AssertionError(
                'Only an editor can submit is_imported translations.')

        # If not an editor, default to submitting a suggestion only.
        just_a_suggestion = not is_editor
        warn_about_lock_timestamp = False

        # Our current submission is newer than 'lock_timestamp'
        # and we try to change it, so just add a suggestion.
        if (not just_a_suggestion and not is_imported and
            self.isTranslationNewerThan(pofile, lock_timestamp)):
            just_a_suggestion = True
            warn_about_lock_timestamp = True

        return just_a_suggestion, warn_about_lock_timestamp


    def updateTranslation(self, pofile, submitter, new_translations,
                          is_imported, lock_timestamp, force_suggestion=False,
                          ignore_errors=False, force_edition_rights=False):
        """See `IPOTMsgSet`."""
        assert self.potemplate == pofile.potemplate, (
            "The template for the translation file and this message doesn't"
            " match.")

        just_a_suggestion, warn_about_lock_timestamp = (
            self._isTranslationMessageASuggestion(force_suggestion,
                                                  pofile, submitter,
                                                  force_edition_rights,
                                                  is_imported,
                                                  lock_timestamp))

        # If the update is on the translation credits message, yet
        # update is not is_imported, silently return.
        if self.is_translation_credit and not is_imported:
            return None

        # Sanitize translations
        sanitized_translations = self._sanitizeTranslations(
            new_translations, pofile.plural_forms)
        # Check that the translations are correct.
        validation_status = self._validate_translations(
            sanitized_translations, ignore_errors)

        # Find all POTranslation records for strings we need.
        potranslations = self._findPOTranslations(sanitized_translations)

        # Find an existing TranslationMessage with exactly the same set
        # of translations.  None if there is no such message and needs to be
        # created.
        matching_message = self._findTranslationMessage(
            pofile, potranslations, pofile.plural_forms)

        if matching_message is None:
            # Creating a new message.

            if is_imported:
                origin = RosettaTranslationOrigin.SCM
            else:
                origin = RosettaTranslationOrigin.ROSETTAWEB

            assert TranslationConstants.MAX_PLURAL_FORMS == 6, (
                "Change this code to support %d plural forms."
                % TranslationConstants.MAX_PLURAL_FORMS)

            matching_message = TranslationMessage(
                potmsgset=self,
                potemplate=pofile.potemplate,
                pofile=pofile,
                language=pofile.language,
                variant=pofile.variant,
                origin=origin,
                submitter=submitter,
                msgstr0=potranslations[0],
                msgstr1=potranslations[1],
                msgstr2=potranslations[2],
                msgstr3=potranslations[3],
                msgstr4=potranslations[4],
                msgstr5=potranslations[5],
                validation_status=validation_status)

            if just_a_suggestion:
                # Adds suggestion karma: editors get their translations
                # automatically approved, so they get 'reviewer' karma
                # instead.
                submitter.assignKarma(
                    'translationsuggestionadded',
                    product=self.potemplate.product,
                    distribution=self.potemplate.distribution,
                    sourcepackagename=self.potemplate.sourcepackagename)
        else:
            # There is an existing matching message. Update it as needed.
            # Also update validation status if needed
            matching_message.validation_status = validation_status

        if just_a_suggestion:
            # An existing message is just a suggestion, warn if needed.
            if warn_about_lock_timestamp:
                raise TranslationConflict(
                    'The new translations were saved as suggestions to '
                    'avoid possible conflicts. Please review them.')

        else:
            # Set the new current message if it validates ok.
            if (matching_message.validation_status ==
                TranslationValidationStatus.OK):
                # Makes the new_message current if needed and also
                # assignes karma for translation approval
                self._makeTranslationMessageCurrent(
                    pofile, matching_message, is_imported, submitter)

        if is_imported:
            # Note that the message is imported.
            matching_message.is_imported = is_imported

        # We need this sync so we don't set self.isfuzzy to the wrong
        # value because cache problems. See bug #102382 as an example of what
        # happened without having this flag + broken code. Our tests were not
        # able to find the problem.
        # XXX CarlosPerelloMarin 2007-11-14 Is there any way to avoid the
        # sync() call and leave it as syncUpdate? Without it we have cache
        # problems with workflows like the ones in
        # xx-pofile-translate-gettext-error-middle-page.txt so we don't see
        # the successful submissions when there are other errors in the same
        # page.
        matching_message.sync()
        return matching_message

    def applySanityFixes(self, text):
        """See `IPOTMsgSet`."""
        if text is None:
            return None

        # Fix the visual point that users copy & paste from the web interface.
        new_text = self.convertDotToSpace(text)
        # Now, fix the newline chars.
        new_text = self.normalizeNewLines(new_text)
        # Finally, set the same whitespaces at the start/end of the string.
        new_text = self.normalizeWhitespaces(new_text)
        # Also, if it's an empty string, replace it with None.
        # XXX CarlosPerelloMarin 2007-11-16: Until we figure out
        # ResettingTranslations
        if new_text == '':
            new_text = None

        return new_text

    def convertDotToSpace(self, text):
        """See IPOTMsgSet."""
        if u'\u2022' in self.singular_text or u'\u2022' not in text:
            return text

        return text.replace(u'\u2022', ' ')

    def normalizeWhitespaces(self, translation_text):
        """See IPOTMsgSet."""
        if translation_text is None:
            return None

        stripped_singular_text = self.singular_text.strip()
        stripped_translation_text = translation_text.strip()
        new_translation_text = None

        if (len(stripped_singular_text) > 0 and
            len(stripped_translation_text) == 0):
            return ''

        if len(stripped_singular_text) != len(self.singular_text):
            # There are whitespaces that we should copy to the 'text'
            # after stripping it.
            prefix = self.singular_text[:-len(self.singular_text.lstrip())]
            postfix = self.singular_text[len(self.singular_text.rstrip()):]
            new_translation_text = '%s%s%s' % (
                prefix, stripped_translation_text, postfix)
        elif len(stripped_translation_text) != len(translation_text):
            # msgid does not have any whitespace, we need to remove
            # the extra ones added to this text.
            new_translation_text = stripped_translation_text
        else:
            # The text is not changed.
            new_translation_text = translation_text

        return new_translation_text

    def normalizeNewLines(self, translation_text):
        """See IPOTMsgSet."""
        # There are three different kinds of newlines:
        windows_style = u'\r\n'
        mac_style = u'\r'
        unix_style = u'\n'
        # We need the stripped variables because a 'windows' style will be at
        # the same time a 'mac' and 'unix' style.
        stripped_translation_text = translation_text.replace(
            windows_style, u'')
        stripped_singular_text = self.singular_text.replace(
            windows_style, u'')

        # Get the style that uses singular_text.
        original_style = None
        if windows_style in self.singular_text:
            original_style = windows_style

        if mac_style in stripped_singular_text:
            if original_style is not None:
                raise BrokenTextError(
                    "original text (%r) mixes different newline markers" %
                        self.singular_text)
            original_style = mac_style

        if unix_style in stripped_singular_text:
            if original_style is not None:
                raise BrokenTextError(
                    "original text (%r) mixes different newline markers" %
                        self.singular_text)
            original_style = unix_style

        # Get the style that uses the given text.
        translation_style = None
        if windows_style in translation_text:
            translation_style = windows_style

        if mac_style in stripped_translation_text:
            if translation_style is not None:
                raise BrokenTextError(
                    "translation text (%r) mixes different newline markers" %
                        translation_text)
            translation_style = mac_style

        if unix_style in stripped_translation_text:
            if translation_style is not None:
                raise BrokenTextError(
                    "translation text (%r) mixes different newline markers" %
                        translation_text)
            translation_style = unix_style

        if original_style is None or translation_style is None:
            # We don't need to do anything, the text is not changed.
            return translation_text

        # Fix the newline chars.
        return translation_text.replace(translation_style, original_style)

    @property
    def hide_translations_from_anonymous(self):
        """See `IPOTMsgSet`."""
        # msgid_singular.msgid is pre-joined everywhere where
        # hide_translations_from_anonymous is used
        return self.is_translation_credit

    @property
    def is_translation_credit(self):
        """See `IPOTMsgSet`."""
        # msgid_singular.msgid is pre-joined everywhere where
        # is_translation_credit is used
        if self.msgid_singular.msgid not in credit_message_ids:
            return False

        expected_context = credit_message_ids[self.msgid_singular.msgid]
        return expected_context is None or (self.context == expected_context)

    def makeHTMLID(self, suffix=None):
        """See `IPOTMsgSet`."""
        elements = ['msgset', str(self.id)]
        if suffix is not None:
            elements.append(suffix)
        return '_'.join(elements)

    def updatePluralForm(self, plural_form_text):
        """See `IPOTMsgSet`."""
        if plural_form_text is None:
            self.msgid_plural = None
            return
        else:
            # Store the given plural form.
            try:
                pomsgid = POMsgID.byMsgid(plural_form_text)
            except SQLObjectNotFound:
                pomsgid = POMsgID(msgid=plural_form_text)
            self.msgid_plural = pomsgid

    def setSequence(self, potemplate, sequence):
        """See `IPOTMsgSet`."""
        assert self.potemplate == potemplate, (
            'Given potemplate is not correct"')
        self.sequence = sequence
        translation_template_item = TranslationTemplateItem.selectOneBy(
            potmsgset=self, potemplate=potemplate)
        if translation_template_item is not None:
            # Update the sequence for the translation template item.
            if sequence == 0:
                translation_template_item.destroySelf()
            else:
                translation_template_item.sequence = sequence
        elif sequence > 0:
            # Introduce this new entry into the TranslationTemplateItem for
            # later usage.
            TranslationTemplateItem(
                potemplate=potemplate,
                sequence=sequence,
                potmsgset=self)
        else:
            # There is no entry for this potmsgset in TranslationTemplateItem
            # table, neither we need to create one, given that the sequence is
            # zero.
            pass

    def getSequence(self, potemplate):
        """See `IPOTMsgSet`."""
        assert self.potemplate == potemplate, (
            'Given potemplate is not correct"')
        return self.sequence
