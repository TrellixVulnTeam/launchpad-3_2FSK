# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = [
    'TranslationGroup',
    'TranslationGroupSet'
    ]

from zope.component import getUtility
from zope.interface import implements

from sqlobject import (
    ForeignKey, StringCol, SQLMultipleJoin, SQLRelatedJoin,
    SQLObjectNotFound)

from storm.expr import Join
from storm.store import Store

from lp.services.worlddata.interfaces.language import ILanguageSet
from lp.translations.interfaces.translationgroup import (
    ITranslationGroup, ITranslationGroupSet)
from lp.registry.model.product import Product
from lp.registry.model.project import Project
from lp.registry.model.teammembership import TeamParticipation
from lp.translations.model.translator import Translator
from canonical.launchpad.webapp.interfaces import NotFoundError

from canonical.database.sqlbase import SQLBase
from canonical.database.constants import DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol

from lp.registry.interfaces.person import validate_public_person


class TranslationGroup(SQLBase):
    """A TranslationGroup."""

    implements(ITranslationGroup)

    # default to listing alphabetically
    _defaultOrder = 'name'

    # db field names
    name = StringCol(unique=True, alternateID=True, notNull=True)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=True)
    datecreated = UtcDateTimeCol(notNull=True, default=DEFAULT)
    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)

    # useful joins
    distributions = SQLMultipleJoin('Distribution',
        joinColumn='translationgroup')
    languages = SQLRelatedJoin('Language', joinColumn='translationgroup',
        intermediateTable='Translator', otherColumn='language')
    translators = SQLMultipleJoin('Translator',
                                  joinColumn='translationgroup')
    translation_guide_url = StringCol(notNull=False, default=None)

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
        return Translator.selectOneBy(language=language,
                                      translationgroup=self)

    @property
    def products(self):
        return Product.selectBy(translationgroup=self.id, active=True)

    @property
    def projects(self):
        return Project.selectBy(translationgroup=self.id, active=True)

    # A limit of projects to get for the `top_projects`.
    TOP_PROJECTS_LIMIT = 6

    @property
    def top_projects(self):
        """See `ITranslationGroup`."""
        goal = self.TOP_PROJECTS_LIMIT
        projects = list(self.distributions[:goal])
        found = len(projects)
        if found < goal:
            projects.extend(
                list(self.projects[:goal-found]))
            found = len(projects)
        if found < goal:
            projects.extend(
                list(self.products[:goal-found]))
        return projects

    @property
    def number_of_remaining_projects(self):
        """See `ITranslationGroup`."""
        total = (
            self.projects.count() +
            self.products.count() +
            self.distributions.count())
        if total > self.TOP_PROJECTS_LIMIT:
            return total - self.TOP_PROJECTS_LIMIT
        else:
            return 0


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

    def new(self, name, title, summary, translation_guide_url, owner):
        """See ITranslationGroupSet."""
        return TranslationGroup(
            name=name,
            title=title,
            summary=summary,
            translation_guide_url=translation_guide_url,
            owner=owner)

    def getByPerson(self, person):
        """See ITranslationGroupSet."""

        store = Store.of(person)
        origin = [
            TranslationGroup,
            Join(Translator,
                Translator.translationgroupID == TranslationGroup.id),
            Join(TeamParticipation,
                TeamParticipation.teamID == Translator.translatorID)
            ]
        result = store.using(*origin).find(
            TranslationGroup, TeamParticipation.person == person)

        return result.order_by(TranslationGroup.title)

    def getGroupsCount(self):
        """See ITranslationGroupSet."""
        return TranslationGroup.select().count()

