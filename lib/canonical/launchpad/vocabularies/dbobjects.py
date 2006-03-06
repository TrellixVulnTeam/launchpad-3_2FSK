# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Vocabularies pulling stuff from the database.

You probably don't want to use these classes directly - see the
docstring in __init__.py for details.
"""

__metaclass__ = type

__all__ = [
    'IHugeVocabulary',
    'SQLObjectVocabularyBase',
    'NamedSQLObjectVocabulary',
    'NamedSQLObjectHugeVocabulary',
    'BinaryAndSourcePackageNameVocabulary',
    'BinaryPackageNameVocabulary',
    'BountyVocabulary',
    'BugVocabulary',
    'BugTrackerVocabulary',
    'BugWatchVocabulary',
    'CountryNameVocabulary',
    'DistributionVocabulary',
    'DistributionUsingMaloneVocabulary',
    'DistroReleaseVocabulary',
    'FilteredDistroArchReleaseVocabulary',
    'FilteredDistroReleaseVocabulary',
    'FilteredProductSeriesVocabulary',
    'KarmaCategoryVocabulary',
    'LanguageVocabulary',
    'MilestoneVocabulary',
    'PackageReleaseVocabulary',
    'PersonAccountToMergeVocabulary',
    'POTemplateNameVocabulary',
    'ProcessorVocabulary',
    'ProcessorFamilyVocabulary',
    'ProductReleaseVocabulary',
    'ProductSeriesVocabulary',
    'ProductVocabulary',
    'ProjectVocabulary',
    'SchemaVocabulary',
    'SourcePackageNameVocabulary',
    'SpecificationVocabulary',
    'SpecificationDependenciesVocabulary',
    'SprintVocabulary',
    'TranslationGroupVocabulary',
    'ValidPersonOrTeamVocabulary',
    'ValidTeamMemberVocabulary',
    'ValidTeamOwnerVocabulary',
    ]

from zope.component import getUtility
from zope.interface import implements, Attribute
from zope.schema.interfaces import IVocabulary, IVocabularyTokenized
from zope.schema.vocabulary import SimpleTerm
from zope.security.proxy import isinstance as zisinstance

from sqlobject import AND, OR, CONTAINSSTRING

from canonical.launchpad.helpers import shortlist
from canonical.lp.dbschema import EmailAddressStatus
from canonical.database.sqlbase import SQLBase, quote_like, quote, sqlvalues
from canonical.launchpad.database import (
    Distribution, DistroRelease, Person, SourcePackageRelease,
    SourcePackageName, BugWatch, Sprint, DistroArchRelease, KarmaCategory,
    BinaryPackageName, Language, Milestone, Product, Project, ProductRelease,
    ProductSeries, TranslationGroup, BugTracker, POTemplateName, Schema,
    Bounty, Country, Specification, Bug, Processor, ProcessorFamily,
    BinaryAndSourcePackageName)
from canonical.launchpad.interfaces import (
    IDistribution, IEmailAddressSet, ILaunchBag, IPersonSet, ITeam,
    IMilestoneSet)

class IHugeVocabulary(IVocabulary, IVocabularyTokenized):
    """Interface for huge vocabularies.

    Items in an IHugeVocabulary should have human readable tokens or the
    default UI will suck.
    """

    displayname = Attribute(
        'A name for this vocabulary, to be displayed in the popup window.')

    def toTerm(obj):
        """Convert the given object into an ITokenizedTerm to be rendered in
        the UI.
        """

    def search(query=None):
        """Return an iterable of objects that match the search string.

        Note that what is searched and how the match is the choice of the
        IHugeVocabulary implementation.
        """


class SQLObjectVocabularyBase:
    """A base class for widgets that are rendered to collect values
    for attributes that are SQLObjects, e.g. ForeignKey.

    So if a content class behind some form looks like:

    class Foo(SQLObject):
        id = IntCol(...)
        bar = ForeignKey(...)
        ...

    Then the vocabulary for the widget that captures a value for bar
    should derive from SQLObjectVocabularyBase.
    """
    implements(IVocabulary, IVocabularyTokenized)
    _orderBy = None

    def __init__(self, context=None):
        self.context = context

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.id, obj.title)

    def __iter__(self):
        """Return an iterator which provides the terms from the vocabulary."""
        params = {}
        if self._orderBy:
            params['orderBy'] = self._orderBy
        for obj in self._table.select(**params):
            yield self.toTerm(obj)

    def __len__(self):
        return len(list(iter(self)))

    def __contains__(self, obj):
        # Sometimes this method is called with an SQLBase instance, but
        # z3 form machinery sends through integer ids. This might be due
        # to a bug somewhere.
        if zisinstance(obj, SQLBase):
            found_obj = self._table.selectOne(self._table.q.id == obj.id)
            return found_obj is not None and found_obj == obj
        else:
            found_obj = self._table.selectOne(self._table.q.id == int(obj))
            return found_obj is not None

    def getQuery(self):
        return None

    def getTerm(self, value):
        # Short circuit. There is probably a design problem here since we
        # sometimes get the id and sometimes an SQLBase instance.
        if zisinstance(value, SQLBase):
            return self.toTerm(value)

        try:
            value = int(value)
        except ValueError:
            raise LookupError(value)

        try:
            obj = self._table.selectOne(self._table.q.id == value)
        except ValueError:
            raise LookupError(value)

        if obj is None:
            raise LookupError(value)

        return self.toTerm(obj)

    def getTermByToken(self, token):
        return self.getTerm(token)

    def emptySelectResults(self):
        """Return a SelectResults object without any elements.
        
        This is to be used when no search string is given to the search()
        method of subclasses, in order to be consistent and always return
        a SelectResults object.
        """
        return self._table.select('1 = 2')


class NamedSQLObjectVocabulary(SQLObjectVocabularyBase):
    """A SQLObjectVocabulary base for database tables that have a unique
    *and* ASCII name column.

    Provides all methods required by IHugeVocabulary, although it
    doesn't actually specify this interface since it may not actually
    be huge and require the custom widgets.

    May still want to override toTerm to provide a nicer title and
    search to search on titles or descriptions.
    """
    _orderBy = 'name'

    def toTerm(self, obj):
        return SimpleTerm(obj.id, obj.name, obj.name)

    def getTermByToken(self, token):
        objs = list(self._table.selectBy(name=token))
        if not objs:
            raise LookupError(token)
        return self.toTerm(objs[0])

    def search(self, query):
        """Return terms where query is a subtring of the name"""
        if query:
            return self._table.select(
                CONTAINSSTRING(self._table.q.name, query),
                orderBy=self._orderBy
                )
        return self.emptySelectResults()


class NamedSQLObjectHugeVocabulary(NamedSQLObjectVocabulary):
    """A NamedSQLObjectVocabulary that implements IHugeVocabulary."""

    implements(IHugeVocabulary)
    _orderBy = 'name'
    displayname = None

    def __init__(self, context=None):
        NamedSQLObjectVocabulary.__init__(self, context)
        if self.displayname is None:
            self.displayname = 'Select %s' % self.__class__.__name__


class BasePersonVocabulary:
    """This is a base class to be used by all different Person Vocabularies."""

    _table = Person

    def toTerm(self, obj):
        """Return the term for this object.

        Preference is given to email-based terms, falling back on
        name-based terms when no preferred email exists for the IPerson.
        """
        if obj.preferredemail is not None:
            return SimpleTerm(obj, obj.preferredemail.email, obj.browsername)
        else:
            return SimpleTerm(obj, obj.name, obj.browsername)

    def getTermByToken(self, token):
        """Return the term for the given token.

        If the token contains an '@', treat it like an email. Otherwise,
        treat it like a name.
        """
        if "@" in token:
            # This looks like an email token, so let's do an object
            # lookup based on that.
            email = getUtility(IEmailAddressSet).getByEmail(token)
            if email is None:
                raise LookupError(token)
            return self.toTerm(email.person)
        else:
            # This doesn't look like an email, so let's simply treat
            # it like a name.
            person = getUtility(IPersonSet).getByName(token)
            if person is None:
                raise LookupError(token)
            return self.toTerm(person)


# Country.name may have non-ASCII characters, so we can't use
# NamedSQLObjectVocabulary here.
class CountryNameVocabulary(SQLObjectVocabularyBase):
    """A vocabulary for country names."""

    _table = Country
    _orderBy = 'name'

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.id, obj.name)


class BinaryAndSourcePackageNameVocabulary(SQLObjectVocabularyBase):
    """A vocabulary for searching for binary and sourcepackage names.

    This is useful for, e.g., reporting a bug on a 'package' when a reporter
    often has no idea about whether they mean a 'binary package' or a 'source
    package'.

    The value returned by a widget using this vocabulary will be either an
    ISourcePackageName or an IBinaryPackageName.
    """
    implements(IHugeVocabulary)

    _table = BinaryAndSourcePackageName
    displayname = 'Select a Package'

    def __contains__(self, name):
        # Is this a source or binary package name?
        return self._table.selectOneBy(name=name)

    def getTermByToken(self, token):
        name = self._table.selectOneBy(name=token)
        if name is None:
            raise LookupError(token)
        return self.toTerm(name)

    def search(self, query):
        """Find matching source and binary package names."""
        if not query:
            return self.emptySelectResults()

        query = "name ILIKE '%%' || %s || '%%'" % quote_like(query)
        return self._table.select(query)

    def toTerm(self, obj):
        return SimpleTerm(obj.name, obj.name, obj.name)


class BinaryPackageNameVocabulary(NamedSQLObjectHugeVocabulary):

    _table = BinaryPackageName
    _orderBy = 'name'
    displayname = 'Select a Binary Package'

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.name)

    def search(self, query):
        """Return IBinaryPackageNames matching the query.

        Returns an empty list if query is None or an empty string.
        """
        if not query:
            return self.emptySelectResults()

        query = query.lower()
        return self._table.select(
            "BinaryPackageName.name LIKE '%%' || %s || '%%'"
            % quote_like(query))


class BugVocabulary(SQLObjectVocabularyBase):

    _table = Bug
    _orderBy = 'id'


class BountyVocabulary(SQLObjectVocabularyBase):

    _table = Bounty
    # XXX: no _orderBy?


class BugTrackerVocabulary(SQLObjectVocabularyBase):

    _table = BugTracker
    _orderBy = 'title'


class LanguageVocabulary(SQLObjectVocabularyBase):

    _table = Language
    _orderBy = 'englishname'

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.id, obj.displayname)


class KarmaCategoryVocabulary(NamedSQLObjectVocabulary):

    _table = KarmaCategory
    _orderBy = 'name'


class ProductVocabulary(SQLObjectVocabularyBase):
    implements(IHugeVocabulary)

    _table = Product
    _orderBy = 'displayname'
    displayname = 'Select a Product'

    def __contains__(self, obj):
        # Sometimes this method is called with an SQLBase instance, but
        # z3 form machinery sends through integer ids. This might be due
        # to a bug somewhere.
        where = "active='t' AND id=%d"
        if zisinstance(obj, SQLBase):
            product = self._table.selectOne(where % obj.id)
            return product is not None and product == obj
        else:
            product = self._table.selectOne(where % int(obj))
            return product is not None

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.title)

    def getTermByToken(self, token):
        product = self._table.selectOneBy(name=token, active=True)
        if product is None:
            raise LookupError(token)
        return self.toTerm(product)

    def search(self, query):
        """Returns products where the product name, displayname, title,
        summary, or description contain the given query. Returns an empty list
        if query is None or an empty string.
        """
        if query:
            query = query.lower()
            like_query = "'%%' || %s || '%%'" % quote_like(query)
            fti_query = quote(query)
            sql = "active = 't' AND (name LIKE %s OR fti @@ ftq(%s))" % (
                    like_query, fti_query
                    )
            return self._table.select(sql, orderBy=self._orderBy)
        return self.emptySelectResults()


class ProjectVocabulary(SQLObjectVocabularyBase):
    implements(IHugeVocabulary)

    _table = Project
    _orderBy = 'displayname'
    displayname = 'Select a Project'

    def __contains__(self, obj):
        where = "active='t' and id=%d"
        if zisinstance(obj, SQLBase):
            project = self._table.selectOne(where % obj.id)
            return project is not None and project == obj
        else:
            project = self._table.selectOne(where % int(obj))
            return project is not None

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.title)

    def getTermByToken(self, token):
        project = self._table.selectOneBy(name=token, active=True)
        if project is None:
            raise LookupError(token)
        return self.toTerm(project)

    def search(self, query):
        """Returns projects where the project name, displayname, title,
        summary, or description contain the given query. Returns an empty list
        if query is None or an empty string.
        """
        if query:
            query = query.lower()
            like_query = "'%%' || %s || '%%'" % quote_like(query)
            fti_query = quote(query)
            sql = "active = 't' AND (name LIKE %s OR fti @@ ftq(%s))" % (
                    like_query, fti_query
                    )
            return self._table.select(sql)
        return self.emptySelectResults()


class TranslationGroupVocabulary(NamedSQLObjectVocabulary):

    _table = TranslationGroup

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.title)


class PersonAccountToMergeVocabulary(
        BasePersonVocabulary, SQLObjectVocabularyBase):
    """The set of all non-merged people with at least one email address.

    This vocabulary is a very specialized one, meant to be used only to choose
    accounts to merge. You *don't* want to use it.
    """
    implements(IHugeVocabulary)

    _orderBy = ['displayname']
    displayname = 'Select a Person to Merge'

    def __contains__(self, obj):
        return obj in self._select()

    def _select(self, text=""):
        return getUtility(IPersonSet).findPerson(text)

    def search(self, text):
        """Return people whose fti or email address match :text."""
        if not text:
            return self.emptySelectResults()

        text = text.lower()
        return self._select(text)


class ValidPersonOrTeamVocabulary(
        BasePersonVocabulary, SQLObjectVocabularyBase):
    """The set of valid Persons/Teams in Launchpad.

    A Person is considered valid if he has a preferred email address,
    a password set and Person.merged is None. Teams have no restrictions
    at all, which means that all teams are considered valid.

    This vocabulary is registered as ValidPersonOrTeam, ValidAssignee,
    ValidMaintainer and ValidOwner, because they have exactly the same
    requisites.
    """
    implements(IHugeVocabulary)

    displayname = 'Select a Person or Team'

    # This is what subclasses must change if they want any extra filtering of
    # results.
    extra_clause = ""

    def __contains__(self, obj):
        return obj in self._doSearch()

    def _doSearch(self, text=""):
        """Return the people/teams whose fti or email address match :text:"""
        if self.extra_clause:
            extra_clause = " AND %s" % self.extra_clause
        else:
            extra_clause = ""

        if not text:
            query = 'Person.id = ValidPersonOrTeamCache.id' + extra_clause
            return Person.select(query, clauseTables=['ValidPersonOrTeamCache'])

        name_match_query = """
            Person.id = ValidPersonOrTeamCache.id
            AND Person.fti @@ ftq(%s)
            """ % quote(text)
        name_match_query += extra_clause
        name_matches = Person.select(
            name_match_query, clauseTables=['ValidPersonOrTeamCache'])

        # Note that we must use lower(email) LIKE rather than ILIKE
        # as ILIKE no longer appears to be hitting the index under PG8.0
        email_match_query = """
            EmailAddress.person = Person.id
            AND EmailAddress.person = ValidPersonOrTeamCache.id
            AND EmailAddress.status IN %s
            AND lower(email) LIKE %s || '%%'
            """ % (sqlvalues(EmailAddressStatus.VALIDATED,
                             EmailAddressStatus.PREFERRED),
                   quote_like(text))
        email_match_query += extra_clause
        email_matches = Person.select(
            email_match_query, 
            clauseTables=['ValidPersonOrTeamCache', 'EmailAddress'])

        # XXX: We have to explicitly provide an orderBy here as a workaround
        # for https://launchpad.net/products/launchpad/+bug/30053
        # -- Guilherme Salgado, 2006-01-30
        return name_matches.union(
            email_matches, orderBy=['displayname', 'name'])

    def search(self, text):
        """Return people/teams whose fti or email address match :text."""
        if not text:
            return self.emptySelectResults()

        text = text.lower()
        return self._doSearch(text=text)


class ValidTeamMemberVocabulary(ValidPersonOrTeamVocabulary):
    """The set of valid members of a given team.

    With the exception of all teams that have this team as a member and the
    team itself, all valid persons and teams are valid members.
    """

    def __init__(self, context):
        if not context:
            raise AssertionError('ValidTeamMemberVocabulary needs a context.')
        if ITeam.providedBy(context):
            self.team = context
        else:
            raise AssertionError(
                "ValidTeamMemberVocabulary's context must implement ITeam."
                "Got %s" % str(context))

        ValidPersonOrTeamVocabulary.__init__(self, context)
        self.extra_clause = """
            Person.id NOT IN (
                SELECT team FROM TeamParticipation 
                WHERE person = %d
                ) AND Person.id != %d
            """ % (self.team.id, self.team.id)


class ValidTeamOwnerVocabulary(ValidPersonOrTeamVocabulary):
    """The set of Persons/Teams that can be owner of a team.

    With the exception of the team itself and all teams owned by that team,
    all valid persons and teams are valid owners for the team.
    """

    def __init__(self, context):
        if not context:
            raise AssertionError('ValidTeamOwnerVocabulary needs a context.')
        if not ITeam.providedBy(context):
            raise AssertionError(
                    "ValidTeamOwnerVocabulary's context must be a team.")
        ValidPersonOrTeamVocabulary.__init__(self, context)
        self.extra_clause = """
            (person.teamowner != %d OR person.teamowner IS NULL) AND
            person.id != %d""" % (context.id, context.id)


class ProductReleaseVocabulary(SQLObjectVocabularyBase):
    implements(IHugeVocabulary)

    displayname = 'Select a Product Release'
    _table = ProductRelease
    # XXX carlos Perello Marin 2005-05-16:
    # Sorting by version won't give the expected results, because it's just a
    # text field.  e.g. ["1.0", "2.0", "11.0"] would be sorted as ["1.0",
    # "11.0", "2.0"].
    # See https://launchpad.ubuntu.com/malone/bugs/687
    _orderBy = [Product.q.name, ProductSeries.q.name,
                ProductRelease.q.version]
    _clauseTables = ['Product', 'ProductSeries']

    def toTerm(self, obj):
        productrelease = obj
        productseries = productrelease.productseries
        product = productseries.product

        # NB: We use '/' as the seperator because '-' is valid in
        # a product.name or productseries.name
        token = '%s/%s/%s' % (
                    product.name, productseries.name, productrelease.version)
        return SimpleTerm(
            obj.id, token, '%s %s %s' % (
                product.name, productseries.name, productrelease.version))

    def getTermByToken(self, token):
        try:
            productname, productseriesname, productreleaseversion = \
                token.split('/', 2)
        except ValueError:
            raise LookupError(token)

        obj = ProductRelease.selectOne(
            AND(ProductRelease.q.productseriesID == ProductSeries.q.id,
                ProductSeries.q.productID == Product.q.id,
                Product.q.name == productname,
                ProductSeries.q.name == productseriesname,
                ProductRelease.q.version == productreleaseversion
                )
            )
        try:
            return self.toTerm(obj)
        except IndexError:
            raise LookupError(token)

    def search(self, query):
        """Return terms where query is a substring of the version or name"""
        if not query:
            return self.emptySelectResults()

        query = query.lower()
        objs = self._table.select(
            AND(
                ProductSeries.q.id == ProductRelease.q.productseriesID,
                Product.q.id == ProductSeries.q.productID,
                OR(
                    CONTAINSSTRING(Product.q.name, query),
                    CONTAINSSTRING(ProductSeries.q.name, query),
                    CONTAINSSTRING(ProductRelease.q.version, query)
                    )
                ),
            orderBy=self._orderBy
            )

        return objs


class ProductSeriesVocabulary(SQLObjectVocabularyBase):
    implements(IHugeVocabulary)

    displayname = 'Select a Product Series'
    _table = ProductSeries
    _orderBy = [Product.q.name, ProductSeries.q.name]
    _clauseTables = ['Product']

    def toTerm(self, obj):
        # NB: We use '/' as the seperator because '-' is valid in
        # a product.name or productseries.name
        token = '%s/%s' % (obj.product.name, obj.name)
        return SimpleTerm(
            obj, token, '%s %s' % (obj.product.name, obj.name))

    def getTermByToken(self, token):
        try:
            productname, productseriesname = token.split('/', 1)
        except ValueError:
            raise LookupError(token)

        result = ProductSeries.selectOne('''
                    Product.id = ProductSeries.product AND
                    Product.name = %s AND
                    ProductSeries.name = %s
                    ''' % sqlvalues(productname, productseriesname),
                    clauseTables=['Product'])
        if result is not None:
            return self.toTerm(result)
        raise LookupError(token)

    def search(self, query):
        """Return terms where query is a substring of the name"""
        if not query:
            return self.emptySelectResults()

        query = query.lower()
        objs = self._table.select(
                AND(
                    Product.q.id == ProductSeries.q.productID,
                    OR(
                        CONTAINSSTRING(Product.q.name, query),
                        CONTAINSSTRING(ProductSeries.q.name, query)
                        )
                    ),
                orderBy=self._orderBy
                )
        return objs


class FilteredDistroReleaseVocabulary(SQLObjectVocabularyBase):
    """Describes the releases of a particular distribution."""
    _table = DistroRelease
    _orderBy = 'version'

    def toTerm(self, obj):
        return SimpleTerm(
            obj, obj.id, '%s %s' % (obj.distribution.name, obj.name))

    def __iter__(self):
        kw = {}
        if self._orderBy:
            kw['orderBy'] = self._orderBy
        launchbag = getUtility(ILaunchBag)
        if launchbag.distribution:
            distribution = launchbag.distribution
            for distrorelease in self._table.selectBy(
                distributionID=distribution.id, **kw):
                yield self.toTerm(distrorelease)


class FilteredDistroArchReleaseVocabulary(SQLObjectVocabularyBase):
    """All arch releases of a particular distribution."""

    _table = DistroArchRelease
    _orderBy = ['DistroRelease.version', 'architecturetag', 'id']
    _clauseTables = ['DistroRelease']

    def toTerm(self, obj):
        name = "%s %s (%s)" % (obj.distrorelease.distribution.name,
                               obj.distrorelease.name, obj.architecturetag)
        return SimpleTerm(obj, obj.id, name)

    def __iter__(self):
        distribution = getUtility(ILaunchBag).distribution
        if distribution:
            query = """
                DistroRelease.id = distrorelease AND
                DistroRelease.distribution = %s
                """ % sqlvalues(distribution.id)
            results = self._table.select(
                query, orderBy=self._orderBy, clauseTables=self._clauseTables)
            for distroarchrelease in results:
                yield self.toTerm(distroarchrelease)


class FilteredProductSeriesVocabulary(SQLObjectVocabularyBase):
    """Describes ProductSeries of a particular product."""
    _table = ProductSeries
    _orderBy = ['product', 'name']

    def toTerm(self, obj):
        return SimpleTerm(
            obj, obj.id, '%s %s' % (obj.product.name, obj.name))

    def __iter__(self):
        launchbag = getUtility(ILaunchBag)
        if launchbag.product is not None:
            for series in launchbag.product.serieslist:
                yield self.toTerm(series)


class MilestoneVocabulary(SQLObjectVocabularyBase):
    _table = Milestone
    _orderBy = None

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.id, obj.displayname)

    def __iter__(self):
        launchbag = getUtility(ILaunchBag)
        target = None
        product = launchbag.product
        if product is not None:
            target = product

        distribution = launchbag.distribution
        if distribution is not None:
            target = distribution

        # XXX, Brad Bollenbach, 2006-02-24: Listifying milestones is evil, but
        # we need to sort the milestones by a non-database value, for the user
        # to find the milestone they're looking for (particularly when showing
        # *all* milestones on the person pages.)
        #
        # This fixes an urgent bug though, so I think this problem should be
        # revisited after we've unblocked users.
        if target is not None:
            milestones = shortlist(target.milestones, longest_expected=40)
        else:
            # We can't use context to reasonably filter the milestones, so let's
            # just grab all of them.
            milestones = shortlist(
                getUtility(IMilestoneSet), longest_expected=40)

        for ms in sorted(milestones, key=lambda m: m.displayname):
            yield self.toTerm(ms)


class SpecificationVocabulary(NamedSQLObjectVocabulary):
    """List specifications for the current product or distribution in
    ILaunchBag, EXCEPT for the current spec in LaunchBag if one exists.
    """

    _table = Specification
    _orderBy = 'title'

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.name)

    def __iter__(self):
        launchbag = getUtility(ILaunchBag)
        product = launchbag.product
        if product is not None:
            target = product

        distribution = launchbag.distribution
        if distribution is not None:
            target = distribution

        if target is not None:
            for spec in sorted(target.specifications(), key=lambda a: a.title):
                # we will not show the current specification in the
                # launchbag
                if spec == launchbag.specification:
                    continue
                # we will not show a specification that is blocked on the
                # current specification in the launchbag. this is because
                # the widget is currently used to select new dependencies,
                # and we do not want to introduce circular dependencies.
                if launchbag.specification is not None:
                    if spec in launchbag.specification.all_blocked():
                        continue
                yield SimpleTerm(spec, spec.name, spec.title)


class SpecificationDependenciesVocabulary(NamedSQLObjectVocabulary):
    """List specifications on which the current specification depends."""

    _table = Specification
    _orderBy = 'title'

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.title)

    def __iter__(self):
        launchbag = getUtility(ILaunchBag)
        curr_spec = launchbag.specification

        if curr_spec is not None:
            for spec in sorted(curr_spec.dependencies, key=lambda a: a.title):
                yield SimpleTerm(spec, spec.name, spec.title)


class SprintVocabulary(NamedSQLObjectVocabulary):
    _table = Sprint

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.title)


class BugWatchVocabulary(SQLObjectVocabularyBase):
    _table = BugWatch

    def __iter__(self):
        bug = getUtility(ILaunchBag).bug
        if bug is None:
            raise ValueError('Unknown bug context for Watch list.')

        for watch in bug.watches:
            yield self.toTerm(watch)


class PackageReleaseVocabulary(SQLObjectVocabularyBase):
    _table = SourcePackageRelease
    _orderBy = 'id'

    def toTerm(self, obj):
        return SimpleTerm(
            obj, obj.id, obj.name + " " + obj.version)


class SourcePackageNameVocabulary(NamedSQLObjectHugeVocabulary):

    displayname = 'Select a Source Package'
    _table = SourcePackageName
    _orderBy = 'name'

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.name)

    def search(self, query):
        """Returns names where the sourcepackage contains the given
        query. Returns an empty list if query is None or an empty string.

        """
        if not query:
            return self.emptySelectResults()

        query = query.lower()
        return self._table.select(
            "sourcepackagename.name LIKE '%%' || %s || '%%'"
            % quote_like(query))


class DistributionVocabulary(NamedSQLObjectVocabulary):

    _table = Distribution
    _orderBy = 'name'

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.title)

    def getTermByToken(self, token):
        obj = Distribution.selectOne("name=%s" % sqlvalues(token))
        if obj is None:
            raise LookupError(token)
        else:
            return self.toTerm(obj)

    def search(self, query):
        """Return terms where query is a substring of the name"""
        if not query:
            return self.emptySelectResults()

        query = query.lower()
        like_query = "'%%' || %s || '%%'" % quote_like(query)
        fti_query = quote(query)
        kw = {}
        if self._orderBy:
            kw['orderBy'] = self._orderBy
        return self._table.select("name LIKE %s" % like_query, **kw)


class DistributionUsingMaloneVocabulary:
    """All the distributions that uses Malone officially."""

    implements(IVocabulary, IVocabularyTokenized)

    _orderBy = 'displayname'

    def __init__(self, context=None):
        self.context = context

    def getTermByToken(self, token):
        obj = Distribution.selectOne(
            "official_malone is True AND name=%s" % sqlvalues(token))
        if obj is None:
            raise LookupError(token)
        else:
            return self.getTerm(obj)

    def __iter__(self):
        """Return an iterator which provides the terms from the vocabulary."""
        distributions_using_malone = Distribution.selectBy(
            official_malone=True, orderBy=self._orderBy)
        for distribution in distributions_using_malone:
            yield self.getTerm(distribution)

    def __len__(self):
        return Distribution.selectBy(official_malone=True).count()

    def __contains__(self, obj):
        return IDistribution.providedBy(obj) and obj.official_malone

    def getQuery(self):
        return None

    def getTerm(self, obj):
        if obj not in self:
            raise LookupError(obj)
        return SimpleTerm(obj, obj.name, obj.displayname)

    def getTermByToken(self, token):
        found_dist = Distribution.selectOneBy(name=token, official_malone=True)
        if found_dist is None:
            raise LookupError(token)
        return self.getTerm(found_dist)


class DistroReleaseVocabulary(NamedSQLObjectVocabulary):

    _table = DistroRelease
    _orderBy = [Distribution.q.name, DistroRelease.q.name]
    _clauseTables = ['Distribution']

    def __iter__(self):
        releases = self._table.select(
            DistroRelease.q.distributionID==Distribution.q.id,
            orderBy=self._orderBy, clauseTables=self._clauseTables)
        for release in releases:
            yield self.toTerm(release)

    def toTerm(self, obj):
        # NB: We use '/' as the separator because '-' is valid in
        # a distribution.name
        token = '%s/%s' % (obj.distribution.name, obj.name)
        return SimpleTerm(obj.id, token, obj.title)

    def getTermByToken(self, token):
        try:
            distroname, distroreleasename = token.split('/', 1)
        except ValueError:
            raise LookupError(token)

        obj = DistroRelease.selectOne(AND(Distribution.q.name == distroname,
            DistroRelease.q.name == distroreleasename))
        if obj is None:
            raise LookupError(token)
        else:
            return self.toTerm(obj)

    def search(self, query):
        """Return terms where query is a substring of the name."""
        if not query:
            return self.emptySelectResults()

        query = query.lower()
        objs = self._table.select(
                AND(
                    Distribution.q.id == DistroRelease.q.distributionID,
                    OR(
                        CONTAINSSTRING(Distribution.q.name, query),
                        CONTAINSSTRING(DistroRelease.q.name, query)
                        )
                    ),
                orderBy=self._orderBy
                )
        return objs


class POTemplateNameVocabulary(NamedSQLObjectHugeVocabulary):

    displayname = 'Select a POTemplate'
    _table = POTemplateName
    _orderBy = 'name'

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.translationdomain)


class ProcessorVocabulary(NamedSQLObjectHugeVocabulary):

    displayname = 'Select a Processor'
    _table = Processor
    _orderBy = 'name'

    def search(self, query):
        """Return terms where query is a substring of the name"""
        if not query:
            return self.emptySelectResults()

        query = query.lower()
        processors = self._table.select(
            CONTAINSSTRING(Processor.q.name, query),
            orderBy=self._orderBy
            )
        return processors


class ProcessorFamilyVocabulary(NamedSQLObjectVocabulary):
    _table = ProcessorFamily
    _orderBy = 'name'

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.name, obj.title)


class SchemaVocabulary(NamedSQLObjectHugeVocabulary):
    """See NamedSQLObjectVocabulary."""

    displayname = 'Select a Schema'
    _table = Schema
