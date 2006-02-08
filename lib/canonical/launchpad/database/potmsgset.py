# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['POTMsgSet']

import sets

from zope.interface import implements
from zope.component import getUtility

from sqlobject import ForeignKey, IntCol, StringCol, SQLObjectNotFound
from canonical.database.sqlbase import SQLBase, quote, sqlvalues

from canonical.launchpad.interfaces import (
    IPOTMsgSet, ILanguageSet, NotFoundError, NameNotAvailable)
from canonical.database.constants import UTC_NOW
from canonical.launchpad.database.pomsgid import POMsgID
from canonical.launchpad.database.pomsgset import POMsgSet
from canonical.launchpad.database.pomsgidsighting import POMsgIDSighting
from canonical.launchpad.database.poselection import POSelection
from canonical.launchpad.database.posubmission import POSubmission
from canonical.launchpad.helpers import shortlist


class POTMsgSet(SQLBase):
    implements(IPOTMsgSet)

    _table = 'POTMsgSet'

    primemsgid_ = ForeignKey(foreignKey='POMsgID', dbName='primemsgid',
        notNull=True)
    sequence = IntCol(dbName='sequence', notNull=True)
    potemplate = ForeignKey(foreignKey='POTemplate', dbName='potemplate',
        notNull=True)
    commenttext = StringCol(dbName='commenttext', notNull=False)
    filereferences = StringCol(dbName='filereferences', notNull=False)
    sourcecomment = StringCol(dbName='sourcecomment', notNull=False)
    flagscomment = StringCol(dbName='flagscomment', notNull=False)

    def getCurrentSubmissionsIDs(self, language, pluralform):
        """See IPOTMsgSet."""
        return self._connection.queryAll('''
            SELECT DISTINCT POSubmission.id
            FROM POSubmission
                JOIN POMsgSet ON POSubmission.pomsgset = POMsgSet.id
                JOIN POFile ON (POMsgSet.pofile = POFile.id AND
                                POFile.language = %s)
                JOIN POTMsgSet ON (POMsgSet.potmsgset = POTMsgSet.id AND
                                   POTMsgSet.primemsgid = %s)
                LEFT OUTER JOIN POSelection AS ps1 ON (
                    ps1.activesubmission = POSubmission.id AND
                    ps1.pluralform = %s)
                LEFT OUTER JOIN POSelection AS ps2 ON (
                    ps2.publishedsubmission = POSubmission.id AND
                    ps2.pluralform = %s)
            WHERE
                ps1.id IS NOT NULL OR ps2.id IS NOT NULL
            ''' % sqlvalues(
                language.id, self.primemsgid_ID, pluralform, pluralform))

    def getCurrentSubmissions(self, language, pluralform):
        """See IPOTMsgSet"""
        posubmission_ids = self.getCurrentSubmissionsIDs(language, pluralform)

        if len(posubmission_ids) > 0:
            ids = [str(L[0]) for L in posubmission_ids]

            posubmissions = POSubmission.select(
                'POSubmission.id IN (%s)' % ', '.join(ids),
                orderBy='-datecreated')

            return shortlist(posubmissions)
        else:
            return []

    def flags(self):
        if self.flagscomment is None:
            return []
        else:
            return [flag
                    for flag in self.flagscomment.replace(' ', '').split(',')
                    if flag != '']

    def messageIDs(self):
        """See IPOTMsgSet."""
        results = POMsgID.select('''
            POMsgIDSighting.potmsgset = %d AND
            POMsgIDSighting.pomsgid = POMsgID.id AND
            POMsgIDSighting.inlastrevision = TRUE
            ''' % self.id,
            clauseTables=['POMsgIDSighting'],
            orderBy='POMsgIDSighting.pluralform')

        for pomsgid in results:
            yield pomsgid

    def getPOMsgIDSighting(self, pluralForm):
        """See IPOTMsgSet."""
        sighting = POMsgIDSighting.selectOneBy(
            potmsgsetID=self.id,
            pluralform=pluralForm,
            inlastrevision=True)
        if sighting is None:
            raise NotFoundError(pluralForm)
        else:
            return sighting

    def getPOMsgSet(self, language_code, variant=None):
        """See IPOTMsgSet."""
        if variant is None:
            variantspec = 'IS NULL'
        else:
            variantspec = ('= %s' % quote(variant))

        return POMsgSet.selectOne('''
            POMsgSet.potmsgset = %d AND
            POMsgSet.pofile = POFile.id AND
            POFile.language = Language.id AND
            POFile.variant %s AND
            Language.code = %s
            ''' % (self.id,
                   variantspec,
                   quote(language_code)),
            clauseTables=['POFile', 'Language'])

    def translationsForLanguage(self, language):
        # To start with, find the number of plural forms. We either want the
        # number set for this specific pofile, or we fall back to the
        # default for the language.

        languages = getUtility(ILanguageSet)
        try:
            pofile = self.potemplate.getPOFileByLang(language)
            pluralforms = pofile.pluralforms
        except KeyError:
            pofile = None
            pluralforms = languages[language].pluralforms

        # If we only have a msgid, we change pluralforms to 1, if it's a
        # plural form, it will be the number defined in the pofile header.
        if len(list(self.messageIDs())) == 1:
            pluralforms = 1

        if pluralforms == None:
            raise RuntimeError(
                "Don't know the number of plural forms for this POT file!")

        # if we have no po file, then return empty translations
        if pofile is None:
            return [None] * pluralforms

        # Find the sibling message set.
        translation_set = POMsgSet.selectOne('''
            POMsgSet.pofile = %d AND
            POMsgSet.potmsgset = POTMsgSet.id AND
            POTMsgSet.primemsgid = %d'''
           % (pofile.id, self.primemsgid_.id),
           clauseTables = ['POTMsgSet'])

        if translation_set is None:
            return [None] * pluralforms

        return translation_set.active_texts

    def makeMessageIDSighting(self, text, pluralForm, update=False):
        """See IPOTMsgSet."""
        try:
            messageID = POMsgID.byMsgid(text)
        except SQLObjectNotFound:
            messageID = POMsgID(msgid=text)

        existing = POMsgIDSighting.selectOneBy(
            potmsgsetID=self.id,
            pomsgid_ID=messageID.id,
            pluralform=pluralForm)

        if existing is None:
            return POMsgIDSighting(
                potmsgsetID=self.id,
                pomsgid_ID=messageID.id,
                datefirstseen=UTC_NOW,
                datelastseen=UTC_NOW,
                inlastrevision=True,
                pluralform=pluralForm)
        else:
            if not update:
                raise NameNotAvailable(
                    "There is already a message ID sighting for this "
                    "message set, text, and plural form")
            existing.set(datelastseen=UTC_NOW, inlastrevision=True)
            return existing

    def apply_sanity_fixes(self, text):
        """See IPOTMsgSet."""

        # Fix the visual point that users copy & paste from the web interface.
        new_text = self.convert_dot_to_space(text)
        # And now set the same whitespaces at the start/end of the string.
        new_text = self.normalize_whitespaces(new_text)

        return new_text

    def convert_dot_to_space(self, text):
        """See IPOTMsgSet."""
        if u'\u2022' in self.primemsgid_.msgid or u'\u2022' not in text:
            return text

        return text.replace(u'\u2022', ' ')

    def normalize_whitespaces(self, text):
        """See IPOTMsgSet."""
        if text is None:
            return text

        msgid = self.primemsgid_.msgid
        stripped_msgid = msgid.strip()
        stripped_text = text.strip()
        new_text = None

        if len(stripped_msgid) > 0 and len(stripped_text) == 0:
            return ''

        if len(stripped_msgid) != len(msgid):
            # There are whitespaces that we should copy to the 'text'
            # after stripping it.
            prefix = msgid[:-len(msgid.lstrip())]
            postfix = msgid[len(msgid.rstrip()):]
            new_text = '%s%s%s' % (prefix, stripped_text, postfix)
        elif len(stripped_text) != len(text):
            # msgid does not have any whitespace, we need to remove
            # the extra ones added to this text.
            new_text = stripped_text
        else:
            # The text is not changed.
            new_text = text

        return new_text
