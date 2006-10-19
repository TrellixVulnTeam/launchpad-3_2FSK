# Copyright 2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['TranslationGroup', 'TranslationGroupSet']

from zope.component import getUtility
from zope.interface import implements

from sqlobject import (
    DateTimeCol, ForeignKey, StringCol, SQLMultipleJoin, SQLRelatedJoin,
    SQLObjectNotFound)

from canonical.launchpad.interfaces import (
    ILanguageSet, ITranslationGroup, ITranslationGroupSet, NotFoundError)

from canonical.database.sqlbase import SQLBase
from canonical.database.constants import DEFAULT

from canonical.launchpad.database.translator import Translator


class TranslationGroup(SQLBase):
    """A TranslationGroup."""

    implements(ITranslationGroup)

    # default to listing alphabetically
    _defaultOrder = 'name'

    # db field names
    name = StringCol(unique=True, alternateID=True, notNull=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    datecreated = DateTimeCol(notNull=True, default=DEFAULT)
    owner = ForeignKey(dbName='owner', foreignKey='Person', notNull=True)

    # useful joins
    products = SQLMultipleJoin('Product', joinColumn='translationgroup')
    projects = SQLMultipleJoin('Project', joinColumn='translationgroup')
    distributions = SQLMultipleJoin('Distribution',
        joinColumn='translationgroup')
    languages = SQLRelatedJoin('Language', joinColumn='translationgroup',
        intermediateTable='Translator', otherColumn='language')
    translators = SQLMultipleJoin('Translator', joinColumn='translationgroup')

    # used to note additions
    def add(self, content):
        """See ITranslationGroup."""
        return content

    # adding and removing translators
    def remove_translator(self, translator):
        """See ITranslationGroup."""
        Translator.delete(translator.id)

    # get a translator by language or code
    def query_translator(self, language):
        """See ITranslationGroup."""
        return Translator.selectOneBy(language=language, translationgroup=self)

    # get a translator by code
    def __getitem__(self, code):
        """See ITranslationGroup."""
        language_set = getUtility(ILanguageSet)
        language = language_set[code]
        result = Translator.selectOneBy(language=language,
                                        translationgroup=self)
        if result is None:
            raise NotFoundError, code
        return result


class TranslationGroupSet:

    implements(ITranslationGroupSet)

    title = 'Rosetta Translation Groups'

    def __iter__(self):
        """See ITranslationGroupSet."""
        for group in TranslationGroup.select():
            yield group

    def __getitem__(self, name):
        """See ITranslationGroupSet."""
        try:
            return TranslationGroup.byName(name)
        except SQLObjectNotFound:
            raise NotFoundError, name

    def new(self, name, title, summary, owner):
        """See ITranslationGroupSet."""
        return TranslationGroup(
            name=name,
            title=title,
            summary=summary,
            owner=owner)

