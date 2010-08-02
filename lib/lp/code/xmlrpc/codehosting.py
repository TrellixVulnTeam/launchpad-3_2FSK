# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementations of the XML-RPC APIs for codehosting."""

__metaclass__ = type
__all__ = [
    'CodehostingAPI',
    'datetime_from_tuple',
    ]


import datetime

import pytz

from bzrlib.urlutils import escape, unescape

from zope.component import getUtility
from zope.interface import implements
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy
from zope.security.management import endInteraction

from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.webapp import LaunchpadXMLRPCView
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.interaction import setupInteractionForPerson
from canonical.launchpad.webapp.interfaces import (
    NameLookupFailed, NotFoundError)
from canonical.launchpad.xmlrpc import faults
from canonical.launchpad.xmlrpc.helpers import return_fault

from lp.code.errors import UnknownBranchTypeError
from lp.code.bzr import BranchFormat, ControlFormat, RepositoryFormat
from lp.code.enums import BranchType
from lp.code.interfaces.branch import BranchCreationException
from lp.code.interfaces.branchlookup import IBranchLookup
from lp.code.interfaces.branchnamespace import (
    InvalidNamespace, lookup_branch_namespace, split_unique_name)
from lp.code.interfaces import branchpuller
from lp.code.interfaces.codehosting import (
    BRANCH_ALIAS_PREFIX, BRANCH_TRANSPORT, CONTROL_TRANSPORT, ICodehostingAPI,
    LAUNCHPAD_ANONYMOUS, LAUNCHPAD_SERVICES)
from lp.code.interfaces.linkedbranch import NoLinkedBranch
from lp.registry.interfaces.person import IPersonSet, NoSuchPerson
from lp.registry.interfaces.product import NoSuchProduct
from lp.services.scripts.interfaces.scriptactivity import IScriptActivitySet
from lp.services.utils import iter_split


UTC = pytz.timezone('UTC')


def datetime_from_tuple(time_tuple):
    """Create a datetime from a sequence that quacks like time.struct_time.

    The tm_isdst is (index 8) is ignored. The created datetime uses
    tzinfo=UTC.
    """
    [year, month, day, hour, minute, second, unused, unused, unused] = (
        time_tuple)
    return datetime.datetime(
        year, month, day, hour, minute, second, tzinfo=UTC)


def run_with_login(login_id, function, *args, **kwargs):
    """Run 'function' logged in with 'login_id'.

    The first argument passed to 'function' will be the Launchpad
    `Person` object corresponding to 'login_id'.

    The exception is when the requesting login ID is `LAUNCHPAD_SERVICES`. In
    that case, we'll pass through the `LAUNCHPAD_SERVICES` variable and the
    method will do whatever security proxy hackery is required to provide read
    privileges to the Launchpad services.
    """
    if login_id == LAUNCHPAD_SERVICES or login_id == LAUNCHPAD_ANONYMOUS:
        # Don't pass in an actual user. Instead pass in LAUNCHPAD_SERVICES
        # and expect `function` to use `removeSecurityProxy` or similar.
        return function(login_id, *args, **kwargs)
    if isinstance(login_id, basestring):
        requester = getUtility(IPersonSet).getByName(login_id)
    else:
        requester = getUtility(IPersonSet).get(login_id)
    if requester is None:
        raise NotFoundError("No person with id %s." % login_id)
    setupInteractionForPerson(requester)
    try:
        return function(requester, *args, **kwargs)
    finally:
        endInteraction()



class CodehostingAPI(LaunchpadXMLRPCView):
    """See `ICodehostingAPI`."""

    implements(ICodehostingAPI)

    def acquireBranchToPull(self, branch_type_names):
        """See `ICodehostingAPI`."""
        branch_types = []
        for branch_type_name in branch_type_names:
            try:
                branch_types.append(BranchType.items[branch_type_name])
            except KeyError:
                raise UnknownBranchTypeError(
                    'Unknown branch type: %r' % (branch_type_name,))
        branch = getUtility(branchpuller.IBranchPuller).acquireBranchToPull(
            *branch_types)
        if branch is not None:
            branch = removeSecurityProxy(branch)
            default_branch = branch.target.default_stacked_on_branch
            if default_branch is None:
                default_branch_name = ''
            elif (branch.branch_type == BranchType.MIRRORED
                  and default_branch.private):
                default_branch_name = ''
            else:
                default_branch_name = '/' + default_branch.unique_name
            return (branch.id, branch.getPullURL(), branch.unique_name,
                    default_branch_name, branch.branch_type.name)
        else:
            return ()

    def mirrorFailed(self, branch_id, reason):
        """See `ICodehostingAPI`."""
        branch = getUtility(IBranchLookup).get(branch_id)
        if branch is None:
            return faults.NoBranchWithID(branch_id)
        # The puller runs as no user and may pull private branches. We need to
        # bypass Zope's security proxy to set the mirroring information.
        removeSecurityProxy(branch).mirrorFailed(reason)
        return True

    def recordSuccess(self, name, hostname, started_tuple, completed_tuple):
        """See `ICodehostingAPI`."""
        date_started = datetime_from_tuple(started_tuple)
        date_completed = datetime_from_tuple(completed_tuple)
        getUtility(IScriptActivitySet).recordSuccess(
            name=name, date_started=date_started,
            date_completed=date_completed, hostname=hostname)
        return True

    def _getBranchNamespaceExtras(self, path, requester):
        """Get the branch namespace, branch name and callback for the path.

        If the path defines a full branch path including the owner and branch
        name, then the namespace that is returned is the namespace for the
        owner and the branch target specified.

        If the path uses an lp short name, then we only allow the requester to
        create a branch if they have permission to link the newly created
        branch to the short name target.  If there is an existing branch
        already linked, then BranchExists is raised.  The branch name that is
        used for the linked branch is 'trunk'.  If that name is taken, then we
        try the name of the link target.
        """

    def createBranch(self, login_id, branch_path):
        """See `ICodehostingAPI`."""
        def create_branch(requester):
            import pdb; pdb.set_trace()
            if not branch_path.startswith('/'):
                return faults.InvalidPath(branch_path)
            escaped_path = unescape(branch_path.strip('/'))
            if escaped_path.startswith(BRANCH_ALIAS_PREFIX + '/'):
                escaped_path = escaped_path[len(BRANCH_ALIAS_PREFIX) + 1:]
            try:
                namespace_name, branch_name = split_unique_name(escaped_path)
            except ValueError:
                return faults.PermissionDenied(
                    "Cannot create branch at '%s'" % branch_path)
            try:
                namespace = lookup_branch_namespace(namespace_name)
            except InvalidNamespace:
                return faults.PermissionDenied(
                    "Cannot create branch at '%s'" % branch_path)
            except NoSuchPerson, e:
                return faults.NotFound(
                    "User/team '%s' does not exist." % e.name)
            except NoSuchProduct, e:
                return faults.NotFound(
                    "Project '%s' does not exist." % e.name)
            except NameLookupFailed, e:
                return faults.NotFound(str(e))
            try:
                branch = namespace.createBranch(
                    BranchType.HOSTED, branch_name, requester)
            except LaunchpadValidationError, e:
                msg = e.args[0]
                if isinstance(msg, unicode):
                    msg = msg.encode('utf-8')
                return faults.PermissionDenied(msg)
            except BranchCreationException, e:
                return faults.PermissionDenied(str(e))
            else:
                return branch.id
        return run_with_login(login_id, create_branch)

    def _canWriteToBranch(self, requester, branch):
        """Can `requester` write to `branch`?"""
        if requester == LAUNCHPAD_SERVICES:
            return False
        return (branch.branch_type == BranchType.HOSTED
                and check_permission('launchpad.Edit', branch))

    def requestMirror(self, login_id, branchID):
        """See `ICodehostingAPI`."""
        def request_mirror(requester):
            branch = getUtility(IBranchLookup).get(branchID)
            # We don't really care who requests a mirror of a branch.
            branch.requestMirror()
            return True
        return run_with_login(login_id, request_mirror)

    def branchChanged(self, login_id, branch_id, stacked_on_location,
                      last_revision_id, control_string, branch_string,
                      repository_string):
        """See `ICodehostingAPI`."""
        def branch_changed(requester):
            branch_set = getUtility(IBranchLookup)
            branch = branch_set.get(branch_id)
            if branch is None:
                return faults.NoBranchWithID(branch_id)

            control_format = ControlFormat.get_enum(control_string)
            branch_format = BranchFormat.get_enum(branch_string)
            repository_format = RepositoryFormat.get_enum(repository_string)

            if requester == LAUNCHPAD_SERVICES:
                branch = removeSecurityProxy(branch)

            branch.branchChanged(
                stacked_on_location, last_revision_id, control_format,
                branch_format, repository_format)

            return True

        return run_with_login(login_id, branch_changed)

    def _serializeBranch(self, requester, branch, trailing_path):
        if requester == LAUNCHPAD_SERVICES:
            branch = removeSecurityProxy(branch)
        try:
            branch_id = branch.id
        except Unauthorized:
            raise faults.PermissionDenied()
        if branch.branch_type == BranchType.REMOTE:
            return None
        return (
            BRANCH_TRANSPORT,
            {'id': branch_id,
             'writable': self._canWriteToBranch(requester, branch)},
            trailing_path)

    def _serializeControlDirectory(self, requester, product_path,
                                   trailing_path):
        try:
            namespace = lookup_branch_namespace(product_path)
        except (InvalidNamespace, NotFoundError):
            return
        if not ('.bzr' == trailing_path or trailing_path.startswith('.bzr/')):
            # '.bzr' is OK, '.bzr/foo' is OK, '.bzrfoo' is not.
            return
        default_branch = namespace.target.default_stacked_on_branch
        if default_branch is None:
            return
        try:
            unique_name = default_branch.unique_name
        except Unauthorized:
            return
        return (
            CONTROL_TRANSPORT,
            {'default_stack_on': escape('/' + unique_name)},
            trailing_path)

    def translatePath(self, requester_id, path):
        """See `ICodehostingAPI`."""
        @return_fault
        def translate_path(requester):
            if not path.startswith('/'):
                return faults.InvalidPath(path)
            stripped_path = path.strip('/')
            for first, second in iter_split(stripped_path, '/'):
                first = unescape(first)
                # Is it a branch?
                if first.startswith(BRANCH_ALIAS_PREFIX + '/'):
                    # XXX: 'first' will start with BRANCH_ALIAS_PREFIX on
                    # every iteration of the loop or it never will. So, change
                    # this to be more efficient.
                    try:
                        branch, trailing = getUtility(IBranchLookup).getByLPPath(
                            first[len(BRANCH_ALIAS_PREFIX + '/'):])
                    except (NameLookupFailed, InvalidNamespace, NoLinkedBranch):
                        # XXX: I don't know if this is a good idea. The reason
                        # we're doing it is that getByLPPath thinks that
                        # 'foo/.bzr' is a request for the '.bzr' series of a
                        # product. -- jml
                        continue
                    second = '/'.join([trailing, second]).strip('/')
                else:
                    branch = getUtility(IBranchLookup).getByUniqueName(first)
                if branch is not None:
                    branch = self._serializeBranch(requester, branch, second)
                    if branch is None:
                        break
                    return branch
                # Is it a product control directory?
                product = self._serializeControlDirectory(
                    requester, first, second)
                if product is not None:
                    return product
            raise faults.PathTranslationError(path)
        return run_with_login(requester_id, translate_path)
