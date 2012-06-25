# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database implementation of the branch lookup utility."""

__metaclass__ = type
# This module doesn't export anything. If you want to lookup branches by name,
# then get the IBranchLookup utility.
__all__ = []


from bzrlib.urlutils import escape
from lazr.enum import DBItem
from lazr.uri import (
    InvalidURIError,
    URI,
    )
from sqlobject import SQLObjectNotFound
from storm.expr import (
    And,
    Join,
    Select,
    )
from zope.component import (
    adapts,
    getUtility,
    queryMultiAdapter,
    )
from zope.interface import implements

from lp.app.errors import NameLookupFailed
from lp.app.validators.name import valid_name
from lp.code.errors import (
    CannotHaveLinkedBranch,
    InvalidNamespace,
    NoLinkedBranch,
    NoSuchBranch,
    )
from lp.code.interfaces.branchlookup import (
    IBranchLookup,
    ILinkedBranchTraversable,
    ILinkedBranchTraverser,
    )
from lp.code.interfaces.branchnamespace import IBranchNamespaceSet
from lp.code.interfaces.codehosting import (
    BRANCH_ALIAS_PREFIX,
    BRANCH_ID_ALIAS_PREFIX,
    )
from lp.code.interfaces.linkedbranch import get_linked_to_branch
from lp.code.model.branch import Branch
from lp.registry.enums import PUBLIC_INFORMATION_TYPES
from lp.registry.errors import (
    NoSuchDistroSeries,
    NoSuchSourcePackageName,
    )
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import (
    IDistroSeries,
    IDistroSeriesSet,
    )
from lp.registry.interfaces.person import NoSuchPerson
from lp.registry.interfaces.pillar import IPillarNameSet
from lp.registry.interfaces.product import (
    InvalidProductName,
    IProduct,
    NoSuchProduct,
    )
from lp.registry.interfaces.productseries import NoSuchProductSeries
from lp.registry.model.distribution import Distribution
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.person import Person
from lp.registry.model.product import Product
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.config import config
from lp.services.database.lpstorm import (
    IStore,
    )
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.interfaces import (
    DEFAULT_FLAVOR,
    IStoreSelector,
    MAIN_STORE,
    )


def adapt(provided, interface):
    """Adapt 'obj' to 'interface', using multi-adapters if necessary."""
    required = interface(provided, None)
    if required is not None:
        return required
    try:
        return queryMultiAdapter(provided, interface)
    except TypeError:
        return None


class RootTraversable:
    """Root traversable for linked branch objects.

    Corresponds to '/' in the path. From here, you can traverse to a
    distribution or a product.
    """

    implements(ILinkedBranchTraversable)

    def traverse(self, name, segments):
        """See `ITraversable`.

        :raise NoSuchProduct: If 'name' doesn't match an existing pillar.
        :return: `IPillar`.
        """
        if not valid_name(name):
            raise InvalidProductName(name)
        pillar = getUtility(IPillarNameSet).getByName(name)
        if pillar is None:
            # Actually, the pillar is no such *anything*. The user might be
            # trying to refer to a project, a distribution or a product. We
            # raise a NoSuchProduct error since that's what we used to raise
            # when we only supported product & junk branches.
            raise NoSuchProduct(name)
        return pillar


class _BaseTraversable:
    """Base class for traversable implementations.

    This just defines a very simple constructor.
    """

    def __init__(self, context):
        self.context = context


class ProductTraversable(_BaseTraversable):
    """Linked branch traversable for products.

    From here, you can traverse to a product series.
    """

    adapts(IProduct)
    implements(ILinkedBranchTraversable)

    def traverse(self, name, segments):
        """See `ITraversable`.

        :raises NoSuchProductSeries: if 'name' doesn't match an existing
            series.
        :return: `IProductSeries`.
        """
        series = self.context.getSeries(name)
        if series is None:
            raise NoSuchProductSeries(name, self.context)
        return series


class DistributionTraversable(_BaseTraversable):
    """Linked branch traversable for distributions.

    From here, you can traverse to a distribution series.
    """

    adapts(IDistribution)
    implements(ILinkedBranchTraversable)

    def traverse(self, name, segments):
        """See `ITraversable`."""
        try:
            return getUtility(IDistroSeriesSet).fromSuite(self.context, name)
        except NoSuchDistroSeries:
            sourcepackage = self.context.getSourcePackage(name)
            if sourcepackage is None:
                if segments:
                    raise
                else:
                    raise NoSuchSourcePackageName(name)
            return sourcepackage


class DistroSeriesTraversable:
    """Linked branch traversable for distribution series.

    From here, you can traverse to a source package.
    """

    adapts(IDistroSeries, DBItem)
    implements(ILinkedBranchTraversable)

    def __init__(self, distroseries, pocket):
        self.distroseries = distroseries
        self.pocket = pocket

    def traverse(self, name, segments):
        """See `ITraversable`."""
        sourcepackage = self.distroseries.getSourcePackage(name)
        if sourcepackage is None:
            raise NoSuchSourcePackageName(name)
        return sourcepackage.getSuiteSourcePackage(self.pocket)


class LinkedBranchTraverser:
    """Utility for traversing to objects that can have linked branches."""

    implements(ILinkedBranchTraverser)

    def traverse(self, path):
        """See `ILinkedBranchTraverser`."""
        segments = path.split('/')
        traversable = RootTraversable()
        while segments:
            name = segments.pop(0)
            context = traversable.traverse(name, segments)
            traversable = adapt(context, ILinkedBranchTraversable)
            if traversable is None:
                break
        return context


class BranchLookup:
    """Utility for looking up branches."""

    implements(IBranchLookup)

    def get(self, branch_id, default=None):
        """See `IBranchLookup`."""
        try:
            return Branch.get(branch_id)
        except SQLObjectNotFound:
            return default

    @staticmethod
    def uriToHostingPath(uri):
        """See `IBranchLookup`."""
        schemes = ('http', 'sftp', 'bzr+ssh')
        codehosting_host = URI(config.codehosting.supermirror_root).host
        if uri.scheme in schemes and uri.host == codehosting_host:
            return uri.path.lstrip('/')
        else:
            return None

    def _uriHostAllowed(self, uri):
        """Is 'uri' for an allowed host?"""
        host = uri.host
        if host is None:
            host = ''
        allowed_hosts = set(config.codehosting.lp_url_hosts.split(','))
        return host in allowed_hosts

    def getByUrl(self, url):
        """See `IBranchLookup`."""
        if url is None:
            return None
        url = url.rstrip('/')
        try:
            uri = URI(url)
        except InvalidURIError:
            return None

        path = self.uriToHostingPath(uri)
        if path is not None:
            branch, trailing, path = self.getByHostingPath(path)
            if branch is not None:
                return branch

        if uri.scheme == 'lp':
            if not self._uriHostAllowed(uri):
                return None
            try:
                return self.getByLPPath(uri.path.lstrip('/'))[0]
            except (
                CannotHaveLinkedBranch, InvalidNamespace, InvalidProductName,
                NoSuchBranch, NoSuchPerson, NoSuchProduct,
                NoSuchProductSeries, NoSuchDistroSeries,
                NoSuchSourcePackageName, NoLinkedBranch):
                return None

        return Branch.selectOneBy(url=url)

    def getByHostingPath(self, path):
        if path.startswith(BRANCH_ID_ALIAS_PREFIX + '/'):
            return self._getBranchByIdAlias(path) + (True,)
        elif path.startswith(BRANCH_ALIAS_PREFIX + '/'):
            return self.getBranchByAlias(path) + (False,)
        else:
            branch, second = self.getContainingBranch(path)
            if second is not None:
                trailing = escape(second)
            else:
                trailing = None
            return branch, trailing, False

    def _getBranchByIdAlias(self, stripped_path):
        try:
            parts = stripped_path.split('/', 2)
            branch_id = int(parts[1])
        except (ValueError, IndexError):
            return None, None
        branch = self.get(branch_id)
        trailing = '/'.join([''] + parts[2:])
        return branch, trailing

    def getBranchByAlias(self, path):
        lp_path = path[len(BRANCH_ALIAS_PREFIX + '/'):]
        try:
            branch, trailing = getUtility(IBranchLookup).getByLPPath(lp_path)
            if branch is not None and trailing is None:
                trailing = ''
            return branch, trailing
        except (InvalidProductName, NoLinkedBranch,
                CannotHaveLinkedBranch, NameLookupFailed,
                InvalidNamespace):
            return None, None

    def getContainingBranch(self, path):
        path_mapping = self.candidateUniqueNames(path)
        store = IStore(Branch)
        clause = Branch.unique_name.is_in(path_mapping.keys())
        branch = store.find(Branch, clause).one()
        if branch is None:
            return None, None
        else:
            return branch, path_mapping[branch.unique_name]

    def getByUrls(self, urls):
        """See `IBranchLookup`."""
        return dict((url, self.getByUrl(url)) for url in set(urls))

    def getByUniqueName(self, unique_name):
        """Find a branch by its unique name.

        For product branches, the unique name is ~user/product/branch; for
        source package branches,
        ~user/distro/distroseries/sourcepackagename/branch; for personal
        branches, ~user/+junk/branch.
        """
        # XXX: JonathanLange 2008-11-27 spec=package-branches: Doesn't handle
        # +dev alias.
        try:
            namespace_name, branch_name = unique_name.rsplit('/', 1)
        except ValueError:
            return None
        try:
            namespace_data = getUtility(IBranchNamespaceSet).parse(
                namespace_name)
        except InvalidNamespace:
            return None
        return self._getBranchInNamespace(namespace_data, branch_name)

    def candidateUniqueNames(self, path):
        segments = path.split('/')
        names = ('/'.join(segments[:length]) for length in [3, 5]
                 if len(segments) >= length)
        return dict((name, path[len(name):]) for name in names)

    def getIdAndTrailingPath(self, path, from_slave=False):
        """See `IBranchLookup`. """
        branch, trailing, _ignored = self.getByHostingPath(path.lstrip('/'))
        if (branch is None or
                branch.information_type not in PUBLIC_INFORMATION_TYPES):
            return None, None
        return branch.id, trailing

    def _getBranchInNamespace(self, namespace_data, branch_name):
        if namespace_data['product'] == '+junk':
            return self._getPersonalBranch(
                namespace_data['person'], branch_name)
        elif namespace_data['product'] is None:
            return self._getPackageBranch(
                namespace_data['person'], namespace_data['distribution'],
                namespace_data['distroseries'],
                namespace_data['sourcepackagename'], branch_name)
        else:
            return self._getProductBranch(
                namespace_data['person'], namespace_data['product'],
                branch_name)

    def _getPersonalBranch(self, person, branch_name):
        """Find a personal branch given its path segments."""
        # Avoid circular imports.
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        origin = [Branch, Join(Person, Branch.owner == Person.id)]
        result = store.using(*origin).find(
            Branch, Person.name == person,
            Branch.distroseries == None,
            Branch.product == None,
            Branch.sourcepackagename == None,
            Branch.name == branch_name)
        branch = result.one()
        return branch

    def _getProductBranch(self, person, product, branch_name):
        """Find a product branch given its path segments."""
        # Avoid circular imports.
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        origin = [
            Branch,
            Join(Person, Branch.owner == Person.id),
            Join(Product, Branch.product == Product.id)]
        result = store.using(*origin).find(
            Branch, Person.name == person, Product.name == product,
            Branch.name == branch_name)
        branch = result.one()
        return branch

    def _getPackageBranch(self, owner, distribution, distroseries,
                          sourcepackagename, branch):
        """Find a source package branch given its path segments.

        Only gets unofficial source package branches, that is, branches with
        names like ~jml/ubuntu/jaunty/openssh/stuff.
        """
        # Avoid circular imports.
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        origin = [
            Branch,
            Join(Person, Branch.owner == Person.id),
            Join(SourcePackageName,
                 Branch.sourcepackagename == SourcePackageName.id)]
        result = store.using(*origin).find(
            Branch, Person.name == owner,
            Branch.distroseriesID == Select(
                DistroSeries.id, And(
                    DistroSeries.distribution == Distribution.id,
                    DistroSeries.name == distroseries,
                    Distribution.name == distribution)),
            SourcePackageName.name == sourcepackagename,
            Branch.name == branch)
        branch = result.one()
        return branch

    def getByLPPath(self, path):
        """See `IBranchLookup`."""
        if path.startswith('~'):
            namespace_set = getUtility(IBranchNamespaceSet)
            segments = iter(path.lstrip('~').split('/'))
            branch = namespace_set.traverse(segments)
            suffix = '/'.join(segments)
            if not check_permission('launchpad.View', branch):
                raise NoSuchBranch(path)
        else:
            # If the first element doesn't start with a tilde, then maybe
            # 'path' is a shorthand notation for a branch.
            # Ignore anything following /.bzr
            segments = path.split('/')
            try:
                index = segments.index('.bzr')
            except:
                pass
            else:
                segments = segments[:index]
            prefix = '/'.join(segments)
            object_with_branch_link = getUtility(
                ILinkedBranchTraverser).traverse(prefix)
            branch, bzr_path = self._getLinkedBranchAndPath(
                object_with_branch_link)
            suffix = path[len(bzr_path) + 1:]
        if suffix == '':
            suffix = None
        return branch, suffix

    def _getLinkedBranchAndPath(self, provided):
        """Get the linked branch for 'provided', and the bzr_path.

        :raise CannotHaveLinkedBranch: If 'provided' can never have a linked
            branch.
        :raise NoLinkedBranch: If 'provided' could have a linked branch, but
            doesn't.
        :return: The linked branch, an `IBranch`.
        """
        linked = get_linked_to_branch(provided)
        if not check_permission('launchpad.View', linked.branch):
            raise NoLinkedBranch(provided)
        return linked.branch, linked.bzr_path
