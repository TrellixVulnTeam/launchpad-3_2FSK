# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The vocabularies relating to dependencies of specifications."""

__metaclass__ = type
__all__ = ['SpecificationDepCandidatesVocabulary']

from zope.interface import implements
from zope.schema.vocabulary import SimpleTerm

from canonical.database.sqlbase import quote_like
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.webapp.vocabulary import (
    CountableIterator,
    IHugeVocabulary,
    SQLObjectVocabularyBase,
    )

from lp.blueprints.interfaces.specification import SpecificationFilter
from lp.blueprints.model.specification import Specification


class SpecificationDepCandidatesVocabulary(SQLObjectVocabularyBase):
    """Specifications that could be dependencies of this spec.

    This includes only those specs that are not blocked by this spec
    (directly or indirectly), unless they are already dependencies.

    The current spec is not included.
    """

    implements(IHugeVocabulary)

    _table = Specification
    _orderBy = 'name'
    displayname = 'Select a blueprint'

    def _filter_specs(self, specs):
        """Filter `specs` to remove invalid candidates.

        Invalid candidates are:

         * The spec that we're adding a depdency to,
         * Specs for a different target, and
         * Specs that depend on this one.

        Preventing the last category prevents loops in the dependency graph.
        """
        # XXX intellectronica 2007-07-05: is 100 a reasonable count before
        # starting to warn?
        speclist = shortlist(specs, 100)
        return [spec for spec in speclist
                if (spec != self.context and
                    spec.target == self.context.target
                    and spec not in self.context.all_blocked)]

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.title)

    def getTermByToken(self, token):
        """See `zope.schema.interfaces.IVocabularyTokenized`.

        The tokens for specifications are just the name of the spec.
        """
        spec = self.context.target.getSpecification(token)
        if spec is not None:
            filtered = self._filter_specs([spec])
            if len(filtered) > 0:
                return self.toTerm(filtered[0])
        raise LookupError(token)

    def search(self, query):
        """See `SQLObjectVocabularyBase.search`.

        We find specs where query is in the text of name or title, or matches
        the full text index and then filter out ineligible specs using
        `_filter_specs`.
        """
        if not query:
            return CountableIterator(0, [])
        quoted_query = quote_like(query)
        sql_query = ("""
            (Specification.name LIKE %s OR
             Specification.title LIKE %s OR
             fti @@ ftq(%s))
            """
            % (quoted_query, quoted_query, quoted_query))
        all_specs = Specification.select(sql_query, orderBy=self._orderBy)
        candidate_specs = self._filter_specs(all_specs)
        return CountableIterator(len(candidate_specs), candidate_specs)

    @property
    def _all_specs(self):
        return self.context.target.specifications(
            filter=[SpecificationFilter.ALL],
            prejoin_people=False)

    def __iter__(self):
        return (self.toTerm(spec)
                for spec in self._filter_specs(self._all_specs))

    def __contains__(self, obj):
        return obj in self._all_specs and len(self._filter_specs([obj])) > 0
