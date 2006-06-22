# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['Language', 'LanguageSet']

from zope.interface import implements

from sqlobject import StringCol, IntCol, BoolCol
from sqlobject import SQLRelatedJoin, SQLObjectNotFound
from canonical.database.sqlbase import SQLBase
from canonical.lp.dbschema import EnumCol, TextDirection

from canonical.launchpad.interfaces import (
    ILanguageSet, ILanguage, NotFoundError)


class Language(SQLBase):
    implements(ILanguage)

    _table = 'Language'

    code = StringCol(dbName='code', notNull=True, unique=True,
            alternateID=True)
    nativename = StringCol(dbName='nativename')
    englishname = StringCol(dbName='englishname')
    pluralforms = IntCol(dbName='pluralforms')
    pluralexpression = StringCol(dbName='pluralexpression')
    visible = BoolCol(dbName='visible', notNull=True)
    direction = EnumCol(dbName='direction', notNull=True,
                        schema=TextDirection, default=TextDirection.LTR)

    translators = SQLRelatedJoin('Person', joinColumn='language',
        otherColumn='person', intermediateTable='PersonLanguage')

    countries = SQLRelatedJoin('Country', joinColumn='language',
        otherColumn='country', intermediateTable='SpokenIn')

    @property
    def displayname(self):
        """See ILanguage."""
        return '%s (%s)' % (self.englishname, self.code)

    @property
    def alt_suggestion_language(self):
        """See ILanguage."""
        if self.code in ['pt_BR',]:
            return None
        elif self.code == 'nn':
            return Language.byCode('nb')
        elif self.code == 'nb':
            return Language.byCode('nn')
        codes = self.code.split('_')
        if len(codes) == 2:
            return Language.byCode(codes[0])
        return None

    @property
    def dashedcode(self):
        """See ILanguage"""
        return self.code.replace('_', '-')

    @property
    def abbreviated_text_dir(self):
        """See ILanguage"""
        if self.direction == TextDirection.LTR:
            return 'ltr'
        elif self.direction == TextDirection.RTL:
            return 'rtl'
        else:
            assert False, "unknown text direction"

class LanguageSet:
    implements(ILanguageSet)

    @property
    def common_languages(self):
        return iter(Language.select(
            'visible IS TRUE',
            orderBy='englishname'))

    def __iter__(self):
        """See ILanguageSet."""
        return iter(Language.select(orderBy='englishname'))

    def __getitem__(self, code):
        """See ILanguageSet."""
        assert isinstance(code, basestring), code
        try:
            return Language.byCode(code)
        except SQLObjectNotFound:
            raise NotFoundError, code

    def keys(self):
        """See ILanguageSet."""
        return [language.code for language in Language.select()]

    def canonicalise_language_code(self, code):
        """See ILanguageSet."""

        if '-' in code:
            language, country = code.split('-', 1)

            return "%s_%s" % (language, country.upper())
        else:
            return code

    def codes_to_languages(self, codes):
        """See ILanguageSet."""

        languages = []

        for code in [self.canonicalise_language_code(code) for code in codes]:
            try:
                languages.append(self[code])
            except KeyError:
                pass

        return languages

