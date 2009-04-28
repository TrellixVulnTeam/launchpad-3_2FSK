# Copyright 2007-2009 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = [
    'DummyTranslationMessage',
    'make_plurals_sql_fragment',
    'make_plurals_fragment',
    'TranslationMessage',
    'TranslationMessageSet'
    ]

from datetime import datetime
import pytz

from sqlobject import BoolCol, ForeignKey, SQLObjectNotFound, StringCol
from storm.store import Store
from zope.interface import implements

from canonical.cachedproperty import cachedproperty
from canonical.database.constants import DEFAULT, UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.launchpad.interfaces import (
    ITranslationMessage, ITranslationMessageSet, RosettaTranslationOrigin,
    TranslationConstants, TranslationValidationStatus)
from lp.registry.interfaces.person import validate_public_person


def make_plurals_fragment(fragment, separator):
    """Repeat text fragment for each plural form, separated by separator.

    Inside fragment, use "%(form)d" to represent the applicable plural
    form number.
    """
    return separator.join([
        fragment % {'form': form}
        for form in xrange(TranslationConstants.MAX_PLURAL_FORMS)])


def make_plurals_sql_fragment(fragment, separator="AND"):
    """Compose SQL fragment consisting of clauses for each plural form.

    Creates fragments like "msgstr0 IS NOT NULL AND msgstr1 IS NOT NULL" etc.

    :param fragment: a piece of SQL text to repeat for each msgstr*, using
        "%(form)d" to represent the number of each form: "msgstr%(form)d IS
        NOT NULL".  Parentheses are added.
    :param separator: string to insert between the repeated clauses, e.g.
        "AND" (default) or "OR".  Spaces are added.
    """
    return make_plurals_fragment("(%s)" % fragment, " %s " % separator)


class TranslationMessageMixIn:
    """This class is not designed to be used directly.

    You should inherit from it and implement the full `ITranslationMessage`
    interface to use the methods and properties defined here.
    """

    @cachedproperty
    def plural_forms(self):
        """See `ITranslationMessage`."""
        if self.potmsgset.msgid_plural is None:
            # This message is a singular message.
            return 1
        else:
            if self.language.pluralforms is not None:
                forms = self.language.pluralforms
            else:
                # Don't know anything about plural forms for this
                # language, fallback to the most common case, 2.
                forms = 2
            return forms

    def makeHTMLID(self, suffix=None):
        """See `ITranslationMessage`."""
        elements = [self.language.code]
        if suffix is not None:
            elements.append(suffix)
        return self.potmsgset.makeHTMLID('_'.join(elements))

    def setPOFile(self, pofile):
        """See `ITransationMessage`."""
        self.browser_pofile = pofile


class DummyTranslationMessage(TranslationMessageMixIn):
    """Represents an `ITranslationMessage` where we don't yet HAVE it.

    We do not put TranslationMessages in the database when we only have
    default information. We can represent them from the existing data and
    logic.
    """
    implements(ITranslationMessage)

    def __init__(self, pofile, potmsgset):
        # Check whether we already have a suitable TranslationMessage, in
        # which case, the dummy one must not be used.
        assert potmsgset.getCurrentTranslationMessage(
            pofile.potemplate,
            pofile.language) is None, (
                'This translation message already exists in the database.')

        self.id = None
        self.pofile = pofile
        self.browser_pofile = pofile
        self.potemplate = pofile.potemplate
        self.language = pofile.language
        self.variant = pofile.variant
        self.potmsgset = potmsgset
        UTC = pytz.timezone('UTC')
        self.date_created = datetime.now(UTC)
        self.submitter = None
        self.date_reviewed = None
        self.reviewer = None

        for form in xrange(TranslationConstants.MAX_PLURAL_FORMS):
            setattr(self, 'msgstr%d' % form, None)

        self.comment = None
        self.origin = RosettaTranslationOrigin.ROSETTAWEB
        self.validation_status = TranslationValidationStatus.UNKNOWN
        self.is_current = True
        self.is_complete = False
        self.is_imported = False
        self.is_empty = True
        self.was_obsolete_in_last_import = False
        self.was_complete_in_last_import = False
        if self.potmsgset.msgid_plural is None:
            self.translations = [None]
        else:
            self.translations = [None] * self.plural_forms

    def isHidden(self, pofile):
        """See `ITranslationMessage`."""
        return True

    def getOnePOFile(self):
        """See `ITranslationMessage`."""
        return None

    @property
    def all_msgstrs(self):
        """See `ITranslationMessage`."""
        return [None] * TranslationConstants.MAX_PLURAL_FORMS

    def destroySelf(self):
        """See `ITranslationMessage`."""
        # This object is already non persistent, so nothing needs to be done.
        return


def validate_is_current(self, attr, value):
    """Unset current message before setting this as current.

    :param value: Whether we want this translation message as the new
        current one.

    If there is already another current message, we unset it first.
    """
    assert value is not None, 'is_current field cannot be None.'

    if value and not self.is_current:
        # We are setting this message as the current one. We need to
        # change current one to non current before.
        current_translation_message = (
            self.potmsgset.getCurrentTranslationMessage(
                self.potemplate,
                self.language, self.variant))
        if (current_translation_message is not None and
            current_translation_message.potemplate == self.potemplate):
            current_translation_message.is_current = False
            # We need to flush the old current message before the
            # new one because the database constraints prevent two
            # current messages.
            Store.of(self).add_flush_order(current_translation_message,
                                           self)

    return value

def validate_is_imported(self, attr, value):
    """Unset current imported message before setting this as imported.

    :param value: Whether we want this translation message as the new
        imported one.

    If there is already another imported message, we unset it first.
    """
    assert value is not None, 'is_imported field cannot be None.'

    if value and not self.is_imported:
        # We are setting this message as the current one. We need to
        # change current one to non current before.
        imported_translation_message = (
            self.potmsgset.getImportedTranslationMessage(
                self.potemplate,
                self.language, self.variant))
        if (imported_translation_message is not None and
            imported_translation_message.potemplate == self.potemplate):
            imported_translation_message.is_imported = False
            # We need to flush the old imported message before the
            # new one because the database constraints prevent two
            # imported messages.
            Store.of(self).add_flush_order(imported_translation_message,
                                           self)

    return value


class TranslationMessage(SQLBase, TranslationMessageMixIn):
    implements(ITranslationMessage)

    _table = 'TranslationMessage'

    pofile = ForeignKey(foreignKey='POFile', dbName='pofile', notNull=False)
    browser_pofile = None
    potemplate = ForeignKey(
        foreignKey='POTemplate', dbName='potemplate', notNull=False,
        default=None)
    language = ForeignKey(
        foreignKey='Language', dbName='language', notNull=False, default=None)
    variant = StringCol(dbName='variant', notNull=False, default=None)
    potmsgset = ForeignKey(
        foreignKey='POTMsgSet', dbName='potmsgset', notNull=True)
    date_created = UtcDateTimeCol(
        dbName='date_created', notNull=True, default=UTC_NOW)
    submitter = ForeignKey(
        foreignKey='Person', storm_validator=validate_public_person,
        dbName='submitter',notNull=True)
    date_reviewed = UtcDateTimeCol(
        dbName='date_reviewed', notNull=False, default=None)
    reviewer = ForeignKey(
        dbName='reviewer', foreignKey='Person',
        storm_validator=validate_public_person, notNull=False, default=None)

    assert TranslationConstants.MAX_PLURAL_FORMS == 6, (
        "Change this code to support %d plural forms."
        % TranslationConstants.MAX_PLURAL_FORMS)
    msgstr0 = ForeignKey(foreignKey='POTranslation', dbName='msgstr0',
                         notNull=False, default=DEFAULT)
    msgstr1 = ForeignKey(foreignKey='POTranslation', dbName='msgstr1',
                         notNull=False, default=DEFAULT)
    msgstr2 = ForeignKey(foreignKey='POTranslation', dbName='msgstr2',
                         notNull=False, default=DEFAULT)
    msgstr3 = ForeignKey(foreignKey='POTranslation', dbName='msgstr3',
                         notNull=False, default=DEFAULT)
    msgstr4 = ForeignKey(foreignKey='POTranslation', dbName='msgstr4',
                         notNull=False, default=DEFAULT)
    msgstr5 = ForeignKey(foreignKey='POTranslation', dbName='msgstr5',
                         notNull=False, default=DEFAULT)

    comment = StringCol(
        dbName='comment', notNull=False, default=None)
    origin = EnumCol(
        dbName='origin', notNull=True, schema=RosettaTranslationOrigin)
    validation_status = EnumCol(
        dbName='validation_status', notNull=True,
        schema=TranslationValidationStatus)
    is_current = BoolCol(dbName='is_current', notNull=True, default=False,
                         storm_validator=validate_is_current)
    is_imported = BoolCol(dbName='is_imported', notNull=True, default=False,
                          storm_validator=validate_is_imported)
    was_obsolete_in_last_import = BoolCol(
        dbName='was_obsolete_in_last_import', notNull=True, default=False)

    # XXX jamesh 2008-05-02:
    # This method is not being called anymore.  The Storm
    # validator code doesn't handle getters.
    def _get_was_obsolete_in_last_import(self):
        """Override getter for was_obsolete_in_last_import.

        When the message is not imported makes no sense to use this flag.
        """
        assert self.is_imported, 'The message is not imported.'

        return self._SO_get_was_obsolete_in_last_import()

    @cachedproperty
    def all_msgstrs(self):
        """See `ITranslationMessage`."""
        return [
            getattr(self, 'msgstr%d' % form)
            for form in xrange(TranslationConstants.MAX_PLURAL_FORMS)]

    @cachedproperty
    def translations(self):
        """See `ITranslationMessage`."""
        msgstrs = self.all_msgstrs
        translations = []
        # Return translations for no more plural forms than the POFile knows.
        for msgstr in msgstrs[:self.plural_forms]:
            if msgstr is None:
                translations.append(None)
            else:
                translations.append(msgstr.translation)
        return translations

    @cachedproperty
    def is_complete(self):
        """See `ITranslationMessage`."""
        if self.msgstr0 is None:
            # No translation for default form (plural form zero).  Incomplete.
            return False
        if self.potmsgset.msgid_plural is None:
            # No plural form needed.  Form zero is enough.
            return True
        return None not in self.translations

    @property
    def is_empty(self):
        """See `ITranslationMessage`."""
        for translation in self.translations:
            if translation is not None:
                # There is at least one translation.
                return False
        # We found no translations in this translation_message
        return True

    def isHidden(self, pofile):
        """See `ITranslationMessage`."""
        # If this message is currently used or has been imported,
        # it's not hidden.
        if self.is_current or self.is_imported:
            return False

        # Otherwise, if this suggestions has been reviewed and
        # rejected (i.e. current translation's date_reviewed is
        # more recent than the date of suggestion's date_created),
        # it is hidden.
        # If it has not been reviewed yet, it's not hidden.
        current = self.potmsgset.getCurrentTranslationMessage(
            pofile.potemplate,
            self.language, self.variant)
        # If there is no current translation, none of the
        # suggestions have been reviewed, so they are all shown.
        if current is None:
            return False
        date_reviewed = current.date_reviewed
        # For an imported current translation, no date_reviewed is set.
        if date_reviewed is None:
            date_reviewed = current.date_created
        return date_reviewed > self.date_created

    def getOnePOFile(self):
        """See `ITranslationMessage`."""
        from canonical.launchpad.database import POFile
        clauses = [
            "POFile.potemplate = TranslationTemplateItem.potemplate",
            "TranslationTemplateItem.potmsgset = %s" % (
                sqlvalues(self.potmsgset)),
            "POFile.language = %s" % sqlvalues(self.language),
            ]
        if self.variant is None:
            clauses.append("POFile.variant IS NULL")
        else:
            clauses.append("POFile.variant = %s" % sqlvalues(self.variant))

        pofiles = POFile.select(' AND '.join(clauses),
                                clauseTables=['TranslationTemplateItem'])
        pofile = list(pofiles[:1])
        if len(pofile) > 0:
            return pofile[0]
        else:
            return None

    def converge(self):
        """Make this message shared.

        If there is already a similar message that is shared, this
        message's information is merged into that of the existing one,
        and self is deleted.
        """
        if self.potemplate is None:
            # Already converged.
            return

        # XXX: XXX: I don't think there's a "proper" way to get this at
        # the moment.
        shared = TranslationMessage.get(potemplate=None, potmsgset=self.potmsgset, language=self.language, variant=self.variant, self.translations)

        current = self.potmsgset.getCurrentTranslationMessage(
            potemplate=None, language=self.language, variant=self.variant)
        imported = self.potmsgset.getImportedTranslationMessage(
            potemplate=None, language=self.language, variant=self.variant)

        if shared is None:
            clash_with_shared_current = current and self.is_current
            clash_with_shared_imported = imported and self.is_imported
            if clash_with_shared_current or clash_with_shared_imported:
                # Keep this message diverged, so it won't usurp the
                # current or imported message that the templates share.
                pass
            else:
                # No clashes; simply mark this message as shared.
                self.potemplate = None
        elif self.is_current or self.is_imported:
            # Bequeathe current/imported flags to shared equivalent.
            if self.is_current and current is None:
                shared.is_current = True
            if self.is_imported and imported is None:
                shared.is_imported = True

            # XXX: Actually, we can also drop this message when it is
            # not current/imported but the shared one is.  In other
            # words, we only need to keep this message if it is
            # current but shared is not, or if it is imported but shared
            # is not.
            same_current = (self.is_current == shared.is_current)
            same_imported = (self.is_imported == shared.is_imported)
            if same_current and same_imported:
                # This message is now totally redundant.
                self.destroySelf()
        else:
            # This is a suggestion duplicating an existing shared
            # message.
            self.destroySelf()


class TranslationMessageSet:
    """See `ITranslationMessageSet`."""
    implements(ITranslationMessageSet)

    def getByID(self, ID):
        """See `ILanguageSet`."""
        try:
            return TranslationMessage.get(ID)
        except SQLObjectNotFound:
            return None

    def selectDirect(self, where=None, order_by=None):
        """See `ILanguageSet`."""
        return TranslationMessage.select(where, orderBy=order_by)
