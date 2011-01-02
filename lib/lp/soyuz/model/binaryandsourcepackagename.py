# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = [
    'BinaryAndSourcePackageName',
    'BinaryAndSourcePackageNameVocabulary',
]

from sqlobject import StringCol
from zope.interface import implements
from zope.schema.vocabulary import SimpleTerm

from canonical.database.sqlbase import SQLBase
from canonical.launchpad.webapp.vocabulary import (
    BatchedCountableIterator,
    NamedSQLObjectHugeVocabulary,
    )
from lp.registry.model.sourcepackagename import getSourcePackageDescriptions
from lp.soyuz.interfaces.binarypackagename import IBinaryAndSourcePackageName
from lp.soyuz.model.binarypackagename import getBinaryPackageDescriptions


class BinaryAndSourcePackageName(SQLBase):
    """See IBinaryAndSourcePackageName"""

    implements(IBinaryAndSourcePackageName)

    _table = 'BinaryAndSourcePackageNameView'
    _idName = 'name'
    _idType = unicode
    _defaultOrder = 'name'

    name = StringCol(dbName='name', notNull=True, unique=True,
                     alternateID=True)


class BinaryAndSourcePackageNameIterator(BatchedCountableIterator):
    """Iterator for BinaryAndSourcePackageNameVocabulary.

    Builds descriptions from source and binary descriptions it can
    identify based on the names returned when queried.
    """

    def getTermsWithDescriptions(self, results):
        # Note that we grab first source package descriptions and then
        # binary package descriptions, giving preference to the latter,
        # via the update() call.
        descriptions = getSourcePackageDescriptions(results, use_names=True)
        binary_descriptions = getBinaryPackageDescriptions(results,
                                                           use_names=True)
        descriptions.update(binary_descriptions)
        return [SimpleTerm(obj, obj.name,
                    descriptions.get(obj.name, "Not uploaded"))
                for obj in results]


class BinaryAndSourcePackageNameVocabulary(NamedSQLObjectHugeVocabulary):
    """A vocabulary for searching for binary and sourcepackage names.

    This is useful for, e.g., reporting a bug on a 'package' when a reporter
    often has no idea about whether they mean a 'binary package' or a 'source
    package'.

    The value returned by a widget using this vocabulary will be either an
    ISourcePackageName or an IBinaryPackageName.
    """
    _table = BinaryAndSourcePackageName
    displayname = 'Select a Package'
    _orderBy = 'name'
    iterator = BinaryAndSourcePackageNameIterator

    def getTermByToken(self, token):
        """See `IVocabularyTokenized`."""
        # package names are always lowercase.
        super_class = super(BinaryAndSourcePackageNameVocabulary, self)
        return super_class.getTermByToken(token.lower())
