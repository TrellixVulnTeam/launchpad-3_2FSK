# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = ['Country', 'CountrySet', 'Continent']

from zope.interface import implements

from sqlobject import StringCol, SQLRelatedJoin, ForeignKey

from canonical.database.constants import DEFAULT
from canonical.database.sqlbase import SQLBase
from canonical.launchpad.interfaces import NotFoundError
from lp.services.worlddata.interfaces.country import (
    ICountry, ICountrySet, IContinent)


class Country(SQLBase):
    """A country."""

    implements(ICountry)

    _table = 'Country'

    # default to listing newest first
    _defaultOrder = 'name'

    # db field names
    name = StringCol(dbName='name', unique=True, notNull=True)
    iso3166code2 = StringCol(dbName='iso3166code2', unique=True,
                             notNull=True)
    iso3166code3 = StringCol(dbName='iso3166code3', unique=True,
                             notNull=True)
    title = StringCol(dbName='title', notNull=False, default=DEFAULT)
    description = StringCol(dbName='description')
    continent = ForeignKey(
        dbName='continent', foreignKey='Continent', default=None)
    languages = SQLRelatedJoin(
        'Language', joinColumn='country', otherColumn='language',
        intermediateTable='SpokenIn')


class CountrySet:
    """A set of countries"""

    implements(ICountrySet)

    def __getitem__(self, iso3166code2):
        country = Country.selectOneBy(iso3166code2=iso3166code2)
        if country is None:
            raise NotFoundError(iso3166code2)
        return country

    def __iter__(self):
        for row in Country.select():
            yield row


class Continent(SQLBase):
    """See IContinent."""

    implements(IContinent)

    _table = 'Continent'
    _defaultOrder = ['name', 'id']

    name = StringCol(unique=True, notNull=True)
    code = StringCol(unique=True, notNull=True)
