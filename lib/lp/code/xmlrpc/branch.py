# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# Disable pylint 'should have "self" as first argument' warnings.
# pylint: disable-msg=E0213

"""Branch XMLRPC API."""

__metaclass__ = type
__all__ = [
    'BranchSetAPI', 'IBranchSetAPI', 'IPublicCodehostingAPI',
    'PublicCodehostingAPI']

import os

from zope.component import getUtility
from zope.interface import Interface, implements

from lazr.uri import URI

from canonical.config import config
from lp.bugs.interfaces.bug import IBugSet
from canonical.launchpad.webapp.interfaces import ILaunchBag, NotFoundError
from lp.code.enums import BranchType
from lp.code.interfaces.branch import (
    BranchCreationException, BranchCreationForbidden, IBranch)
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.product import IProductSet
from lp.code.interfaces.branch import NoSuchBranch
from lp.code.interfaces.branchlookup import IBranchLookup
from lp.code.interfaces.branchnamespace import (
    get_branch_namespace, InvalidNamespace)
from lp.code.interfaces.linkedbranch import (
    CannotHaveLinkedBranch, NoLinkedBranch)
from lp.registry.interfaces.distroseries import NoSuchDistroSeries
from lp.registry.interfaces.person import NoSuchPerson
from lp.registry.interfaces.product import (
    InvalidProductName, NoSuchProduct)
from lp.registry.interfaces.productseries import NoSuchProductSeries
from lp.registry.interfaces.sourcepackagename import (
    NoSuchSourcePackageName)
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.webapp import LaunchpadXMLRPCView, canonical_url
from canonical.launchpad.xmlrpc import faults
from canonical.launchpad.xmlrpc.helpers import return_fault


class IBranchSetAPI(Interface):
    """An XMLRPC interface for dealing with branches.

    This XML-RPC interface was introduced to support Bazaar 0.8-2, which is
    included in Ubuntu 6.06. This interface cannot be removed until Ubuntu
    6.06 is end-of-lifed.
    """

    def register_branch(branch_url, branch_name, branch_title,
                        branch_description, author_email, product_name,
                        owner_name=''):
        """Register a new branch in Launchpad."""

    def link_branch_to_bug(branch_url, bug_id, whiteboard):
        """Link the branch to the bug."""


class BranchSetAPI(LaunchpadXMLRPCView):

    implements(IBranchSetAPI)

    def register_branch(self, branch_url, branch_name, branch_title,
                        branch_description, author_email, product_name,
                        owner_name=''):
        """See IBranchSetAPI."""
        registrant = getUtility(ILaunchBag).user
        assert registrant is not None, (
            "register_branch shouldn't be accessible to unauthenicated"
            " requests.")

        person_set = getUtility(IPersonSet)
        if owner_name:
            owner = person_set.getByName(owner_name)
            if owner is None:
                return faults.NoSuchPersonWithName(owner_name)
            if not registrant.inTeam(owner):
                return faults.NotInTeam(registrant.name, owner_name)
        else:
            owner = registrant

        if product_name:
            product = getUtility(IProductSet).getByName(product_name)
            if product is None:
                return faults.NoSuchProduct(product_name)
        else:
            product = None

        # Branch URLs in Launchpad do not end in a slash, so strip any
        # slashes from the end of the URL.
        branch_url = branch_url.rstrip('/')

        branch_lookup = getUtility(IBranchLookup)
        existing_branch = branch_lookup.getByUrl(branch_url)
        if existing_branch is not None:
            return faults.BranchAlreadyRegistered(branch_url)

        try:
            unicode_branch_url = branch_url.decode('utf-8')
            url = IBranch['url'].validate(unicode_branch_url)
        except LaunchpadValidationError, exc:
            return faults.InvalidBranchUrl(branch_url, exc)

        # We want it to be None in the database, not ''.
        if not branch_description:
            branch_description = None
        if not branch_title:
            branch_title = None

        if not branch_name:
            branch_name = unicode_branch_url.split('/')[-1]

        try:
            if branch_url:
                branch_type = BranchType.MIRRORED
            else:
                branch_type = BranchType.HOSTED
            namespace = get_branch_namespace(owner, product)
            branch = namespace.createBranch(
                branch_type=branch_type,
                name=branch_name, registrant=registrant,
                url=branch_url, title=branch_title,
                summary=branch_description)
            if branch_type == BranchType.MIRRORED:
                branch.requestMirror()
        except BranchCreationForbidden:
            return faults.BranchCreationForbidden(product.displayname)
        except BranchCreationException, err:
            return faults.BranchNameInUse(err)
        except LaunchpadValidationError, err:
            return faults.InvalidBranchName(err)

        return canonical_url(branch)

    def link_branch_to_bug(self, branch_url, bug_id, whiteboard):
        """See IBranchSetAPI."""
        branch = getUtility(IBranchLookup).getByUrl(url=branch_url)
        if branch is None:
            return faults.NoSuchBranch(branch_url)
        try:
            bug = getUtility(IBugSet).get(bug_id)
        except NotFoundError:
            return faults.NoSuchBug(bug_id)
        if not whiteboard:
            whiteboard = None

        # Since this API is controlled using launchpad.AnyPerson there must be
        # an authenticated person, so use this person as the registrant.
        registrant = getUtility(ILaunchBag).user
        bug.addBranch(branch, registrant=registrant, whiteboard=whiteboard)
        return canonical_url(bug)


class IPublicCodehostingAPI(Interface):
    """The public codehosting API."""

    def resolve_lp_path(path):
        """Expand the path segment of an lp: URL into a list of branch URLs.

        This method is added to support Bazaar 0.93. It cannot be removed
        until we stop supporting Bazaar 0.93.

        :return: A dict containing a single 'urls' key that maps to a list of
            URLs. Clients should use the first URL in the list that they can
            support.  Returns a Fault if the path does not resolve to a
            branch.
        """


class _NonexistentBranch:
    """Used to represent a branch that was requested but doesn't exist."""

    def __init__(self, unique_name):
        self.unique_name = unique_name
        self.branch_type = None


class PublicCodehostingAPI(LaunchpadXMLRPCView):
    """See `IPublicCodehostingAPI`."""

    implements(IPublicCodehostingAPI)

    supported_schemes = 'bzr+ssh', 'http'

    def _getBazaarHost(self):
        """Return the hostname for the codehosting server."""
        return URI(config.codehosting.supermirror_root).host

    def _getResultDict(self, branch, suffix=None):
        """Return a result dict with a list of URLs for the given branch.

        :param branch: A Branch object.
        :param suffix: The section of the path that follows the branch
            specification.
        :return: {'urls': [list_of_branch_urls]}.
        """
        if branch.branch_type == BranchType.REMOTE:
            if branch.url is None:
                return faults.NoUrlForBranch(branch.unique_name)
            return dict(urls=[branch.url])
        else:
            return self._getUniqueNameResultDict(branch.unique_name, suffix)

    def _getUniqueNameResultDict(self, unique_name, suffix=None):
        result = dict(urls=[])
        host = self._getBazaarHost()
        path = '/' + unique_name
        if suffix is not None:
            path = os.path.join(path, suffix)
        for scheme in self.supported_schemes:
            result['urls'].append(
                str(URI(host=host, scheme=scheme, path=path)))
        return result

    @return_fault
    def _resolve_lp_path(self, path):
        """See `IPublicCodehostingAPI`."""
        # Separate method because Zope's mapply raises errors if we use
        # decorators in XMLRPC methods. mapply checks that the passed
        # arguments match the formal parameters. Decorators normally have
        # *args and **kwargs, which mapply fails on.
        strip_path = path.strip('/')
        if strip_path == '':
            raise faults.InvalidBranchIdentifier(path)
        branch_set = getUtility(IBranchLookup)
        try:
            branch, suffix = branch_set.getByLPPath(strip_path)
        except NoSuchBranch:
            # If the branch isn't found, but it looks like a valid name, then
            # resolve it anyway, treating the path like a branch's unique
            # name. This lets people push new branches up to Launchpad using
            # lp: URL syntax.
            return self._getUniqueNameResultDict(strip_path)
        # XXX: JonathanLange 2009-03-21 bug=347728: All of this is repetitive
        # and thus error prone. Alternatives are directly raising faults from
        # the model code(blech) or some automated way of reraising as faults
        # or using a narrower range of faults (e.g. only one "NoSuch" fault).
        except InvalidProductName, e:
            raise faults.InvalidProductIdentifier(e.name)
        except NoSuchProductSeries, e:
            raise faults.NoSuchProductSeries(e.name, e.product)
        except NoSuchPerson, e:
            raise faults.NoSuchPersonWithName(e.name)
        except NoSuchProduct, e:
            raise faults.NoSuchProduct(e.name)
        except NoSuchDistroSeries, e:
            raise faults.NoSuchDistroSeries(e.name)
        except NoSuchSourcePackageName, e:
            raise faults.NoSuchSourcePackageName(e.name)
        except NoLinkedBranch, e:
            raise faults.NoLinkedBranch(e.component)
        except CannotHaveLinkedBranch, e:
            raise faults.CannotHaveLinkedBranch(e.component)
        except InvalidNamespace, e:
            raise faults.InvalidBranchUniqueName(e.name)
        return self._getResultDict(branch, suffix)

    def resolve_lp_path(self, path):
        """See `IPublicCodehostingAPI`."""
        return self._resolve_lp_path(path)
