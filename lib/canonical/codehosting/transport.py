# Copyright 2004-2007 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0702,W0231

"""The Launchpad code hosting file system.

The way Launchpad presents branches is very different from the way it stores
them. Externally, branches are reached using URLs that look like
<schema>://launchpad.net/~owner/product/branch-name. Internally, they are
stored by branch ID. Branch 1 is stored at 00/00/00/01 and branch 10 is stored
at 00/00/00/0A. Further, these branches might not be stored on the same
physical machine.

This means that our services need to translate the external paths into
internal paths.

We also want to let users create new branches on Launchpad simply by pushing
them up. We want Launchpad to detect when a branch has been changed and update
our internal mirror.

This means our services must detect events like "make directory" and "unlock
branch", translate them into Launchpad operations like "create branch" and
"request mirror" and then actually perform those operations.

So, we have a `LaunchpadServer` which implements the core operations --
translate a path, make a branch and request a mirror -- in terms of virtual
paths.

This server does most of its work by delegating to a `LaunchpadBranch` object.
This object can be constructed from a virtual path and then operated on. It in
turn delegates to the "authserver", an internal XML-RPC server that actually
talks to the database. We cache requests to the authserver using
`CachingAuthserverClient`, in order to speed things up a bit.

We hook the `LaunchpadServer` into Bazaar by implementing a
`AsyncVirtualTransport`, a `bzrlib.transport.Transport` that wraps all of its
operations so that they are translated by an object that implements
`translateVirtualPath`.

This virtual transport isn't quite enough, since it only does dumb path
translation. We also need to be able to interpret filesystem events in terms
of Launchpad branches. To do this, we provide a `LaunchpadTransport` that
hooks into operations like `mkdir` and ask the `LaunchpadServer` to make a
branch if appropriate.
"""

__metaclass__ = type
__all__ = [
    'AsyncLaunchpadTransport',
    'AsyncVirtualTransport',
    'BlockingProxy',
    'get_chrooted_transport',
    'get_puller_server',
    'get_readonly_transport',
    'get_scanner_server',
    'LaunchpadInternalServer',
    'LaunchpadServer',
    'set_up_logging',
    'SynchronousAdapter',
    ]

import logging
import os
import xmlrpclib

from bzrlib.bzrdir import BzrDirFormat
from bzrlib.errors import (
    BzrError, InProcessTransport, NoSuchFile, PermissionDenied,
    TransportNotPossible)
from bzrlib import trace, urlutils
from bzrlib.transport import (
    chroot, get_transport, register_transport, Server, Transport,
    unregister_transport)
from bzrlib.transport.memory import MemoryServer

from twisted.internet import defer
from twisted.python import failure
from twisted.web.xmlrpc import Fault

from canonical.authserver.interfaces import (
    LAUNCHPAD_SERVICES, NOT_FOUND_FAULT_CODE, PERMISSION_DENIED_FAULT_CODE,
    READ_ONLY)

from canonical.codehosting import branch_id_to_path
from canonical.codehosting.bzrutils import ensure_base
from canonical.config import config
from canonical.twistedsupport import gatherResults
from canonical.twistedsupport.loggingsupport import set_up_oops_reporting


# The directories allowed directly beneath a branch directory. These are the
# directories that Bazaar creates as part of regular operation.
ALLOWED_DIRECTORIES = ('.bzr', '.bzr.backup', 'backup.bzr')
FORBIDDEN_DIRECTORY_ERROR = (
    "Cannot create '%s'. Only Bazaar branches are allowed.")


def is_lock_directory(absolute_path):
    """Is 'absolute_path' a Bazaar branch lock directory?"""
    return absolute_path.endswith('/.bzr/branch/lock/held')


def get_chrooted_transport(url):
    """Return a chrooted transport serving `url`."""
    chroot_server = chroot.ChrootServer(get_transport(url))
    chroot_server.setUp()
    return get_transport(chroot_server.get_url())


def get_readonly_transport(transport):
    """Wrap `transport` in a readonly transport."""
    return get_transport('readonly+' + transport.base)


def get_path_segments(path, maximum_segments=-1):
    """Break up the given path into segments.

    If 'path' ends with a trailing slash, then the final empty segment is
    ignored.
    """
    return path.strip('/').split('/', maximum_segments)


class _NotFilter(logging.Filter):
    """A Filter that only allows records that do *not* match.

    A _NotFilter initialized with "A.B" will allow "C", "A.BB" but not allow
    "A.B", "A.B.C" etc.
    """

    def filter(self, record):
        return not logging.Filter.filter(self, record)


def set_up_logging(configure_oops_reporting=False):
    """Set up logging for the smart server.

    This sets up a debugging handler on the 'codehosting' logger, makes sure
    that things logged there won't go to stderr (necessary because of
    bzrlib.trace shenanigans) and then returns the 'codehosting' logger.

    In addition, if configure_oops_reporting is True, install a
    Twisted log observer that ensures unhandled exceptions get
    reported as OOPSes.
    """
    log = logging.getLogger('codehosting')

    if config.codehosting.debug_logfile is not None:
        # Create the directory that contains the debug logfile.
        parent_dir = os.path.dirname(config.codehosting.debug_logfile)
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
        assert os.path.isdir(parent_dir), (
            "%r should be a directory" % parent_dir)

        # Messages logged to 'codehosting' are stored in the debug_logfile.
        handler = logging.FileHandler(config.codehosting.debug_logfile)
        handler.setFormatter(
            logging.Formatter(
                '%(asctime)s %(levelname)-8s %(name)s\t%(message)s'))
        handler.setLevel(logging.DEBUG)
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.CRITICAL)

    # Don't log 'codehosting' messages to stderr.
    if getattr(trace, '_stderr_handler', None) is not None:
        trace._stderr_handler.addFilter(_NotFilter('codehosting'))

    if configure_oops_reporting:
        set_up_oops_reporting('codehosting')

    return log


class BranchNotFound(BzrError):
    """Raised when on translating a virtual path for a non-existent branch."""

    _fmt = ("Could not find id for branch ~%(owner)s/%(product)s/%(name)s.")


class NotABranchPath(BzrError):
    """Raised when we cannot translate a virtual URL fragment to a branch.

    In particular, this is raised when there is some intrinsic deficiency in
    the path itself.
    """

    _fmt = ("Could not translate %(virtual_url_fragment)r to branch. "
            "%(reason)s")


class NotEnoughInformation(NotABranchPath):
    """Raised when there's not enough information in the path."""

    def __init__(self, virtual_url_fragment):
        NotABranchPath.__init__(
            self, virtual_url_fragment=virtual_url_fragment,
            reason="Not enough information.")


class InvalidOwnerDirectory(NotABranchPath):
    """Raised when the owner directory is invalid.

    This generally means that it doesn't start with a tilde (~).
    """

    def __init__(self, virtual_url_fragment):
        NotABranchPath.__init__(
            self, virtual_url_fragment=virtual_url_fragment,
            reason="Path must start with a user or team directory.")


class InvalidControlDirectory(BzrError):
    """Raised when we try to parse an invalid control directory."""


class BlockingProxy:

    def __init__(self, proxy):
        self._proxy = proxy

    def callRemote(self, method_name, *args):
        return getattr(self._proxy, method_name)(*args)


class CachingAuthserverClient:
    """Wrapper for the authserver that caches responses for a particular user.

    This only wraps the methods that are used for serving branches via a
    Bazaar transport: createBranch, getBranchInformation and requestMirror.

    In the normal course of operation, our Bazaar transport translates from
    "virtual branch identifier" (currently '~owner/product/name') to a branch
    ID. It does this many, many times for a single Bazaar operation. Thus, it
    makes sense to cache results from the authserver.
    """

    def __init__(self, authserver, user_id):
        """Construct a caching authserver.

        :param authserver: An XML-RPC proxy that implements callRemote.
        :param user_id: The database ID of the user who will be making these
            requests. An integer.
        """
        self._authserver = authserver
        self._branch_info_cache = {}
        self._stacked_branch_cache = {}
        self._user_id = user_id

    def createBranch(self, owner, product, branch):
        """Create a branch on the authserver.

        This raises any Faults that might be raised by the authserver's
        `createBranch` method, so for more information see
        `IHostedBranchStorage.createBranch`.

        :param owner: The owner of the branch. A string that is the name of a
            Launchpad `IPerson`.
        :param product: The project that the branch belongs to. A string that
            is either '+junk' or the name of a Launchpad `IProduct`.
        :param branch: The name of the branch to create.

        :return: A `Deferred` that fires the ID of the created branch.
        """
        deferred = defer.maybeDeferred(
            self._authserver.callRemote, 'createBranch', self._user_id,
            owner, product, branch)

        def clear_cache_and_maybe_transalte_error(branch_id):
            # Clear the cache for this branch. We *could* populate it with
            # (branch_id, 'w'), but then we'd be building in more assumptions
            # about the authserver.
            self._branch_info_cache[(owner, product, branch)] = None
            # XXX: JonathanLange 2008-04-23: This logic should be moved to the
            # authserver. test_make_product_directory_for_nonexistent_product
            # and test_mkdir_not_team_member_error (in test_filesystem) both
            # fail without this check. Those tests should be moved (or copied)
            # to the authserver level at the same time that this check is.
            if branch_id == '':
                raise xmlrpclib.Fault(
                    PERMISSION_DENIED_FAULT_CODE,
                    'Cannot create branch: ~%s/%s/%s'
                    % (owner, product, branch))
            return branch_id

        return deferred.addCallback(clear_cache_and_maybe_transalte_error)

    def getBranchInformation(self, owner, product, branch):
        """Get branch information from the authserver.

        :param owner: The owner of the branch. A string that is the name of a
            Launchpad `IPerson`.
        :param product: The project that the branch belongs to. A string that
            is either '+junk' or the name of a Launchpad `IProduct`.
        :param branch: The name of the branch that we are interested in.

        :return: A Deferred that fires (branch_id, permissions), where
            'permissions' is WRITABLE if the current user can write to the
            branch, and READ_ONLY if they cannot. If the branch doesn't exist,
            return ('', ''). The "current user" is the user ID passed to the
            constructor.
        """
        branch_info = self._branch_info_cache.get((owner, product, branch))
        if branch_info is not None:
            return defer.succeed(branch_info)

        deferred = defer.maybeDeferred(
            self._authserver.callRemote, 'getBranchInformation',
            self._user_id, owner, product, branch)
        def add_to_cache(branch_info):
            self._branch_info_cache[
                (owner, product, branch)] = branch_info
            return branch_info
        return deferred.addCallback(add_to_cache)

    def getDefaultStackedOnBranch(self, product):
        branch_name = self._stacked_branch_cache.get(product)
        if branch_name is not None:
            return defer.succeed(branch_name)

        deferred = defer.maybeDeferred(
            self._authserver.callRemote, 'getDefaultStackedOnBranch',
            self._user_id, product)
        def add_to_cache(branch_name):
            self._stacked_branch_cache[product] = branch_name
            return branch_name
        return deferred.addCallback(add_to_cache)

    def requestMirror(self, branch_id):
        """Mark a branch as needing to be mirrored.

        :param branch_id: The database ID of the branch.
        """
        return defer.maybeDeferred(
            self._authserver.callRemote, 'requestMirror', self._user_id,
            branch_id)


class LaunchpadBranch:
    """A branch on Launchpad.

    This abstractly represents a branch on Launchpad without exposing details
    of the naming of Launchpad branches. It contains and maintains the
    knowledge of how a virtual path, such as '~owner/product/branch' is
    translated into the underlying storage systems.

    It also exposes operations on Launchpad branches that we in turn expose
    via the codehosting system. Namely, creating a branch and requesting that
    a branch be mirrored.
    """

    @classmethod
    def from_virtual_path(cls, authserver, virtual_url_fragment):
        """Construct a LaunchpadBranch from a virtual URL fragment.

        :param authserver: An XML-RPC client to the Launchpad authserver.
            This is used to get information about the branch and to perform
            database operations on the branch. This XML-RPC client should
            implement 'callRemote'.
        :param virtual_path: A public path to a branch, or to a file or
            directory within a branch. This path is required to be URL
            escaped.

        :raise NotABranchPath: If `virtual_path` cannot be translated into a
            (potential) path to a branch. See also `NotEnoughInformation`
            and `InvalidOwnerDirectory`.

        :return: (launchpad_branch, rest_of_path), where `launchpad_branch`
            is an instance of LaunchpadBranch that represents the branch at
            the virtual path, and `rest_of_path` is a URL fragment within
            that branch.
        """
        virtual_path = urlutils.unescape(virtual_url_fragment).encode('utf-8')
        segments = get_path_segments(virtual_path, 3)
        # If we don't have at least an owner, product and name, then we don't
        # have enough information for a branch.
        if len(segments) < 3:
            raise NotEnoughInformation(virtual_path)
        # If we have only an owner, product, name tuple, append an empty path.
        if len(segments) == 3:
            segments.append('')
        user_dir, product, name, path = segments
        # The Bazaar client will look for a .bzr directory in the owner and
        # product directories to see if there's a shared repository. There
        # won't be, so we should treat this case the same as trying to access
        # a branch without enough information.
        if '.bzr' in (user_dir, product, name):
            raise NotEnoughInformation(virtual_path)
        if not user_dir.startswith('~'):
            raise InvalidOwnerDirectory(virtual_path)
        escaped_path = urlutils.escape(path)
        return cls(authserver, user_dir[1:], product, name), escaped_path

    def __init__(self, authserver, owner, product, name):
        """Construct a LaunchpadBranch object.

        In general, don't call this directly, use
        `LaunchpadBranch.from_virtual_path` instead. This prevents assumptions
        about branch naming spreading throughout the code.

        :param authserver: An XML-RPC client to the Launchpad authserver.
            This is used to get information about the branch and to perform
            database operations on the branch. The client should implement
            `callRemote`.
        :param owner: The owner of the branch. A string that is the name of a
            Launchpad `IPerson`.
        :param product: The project that the branch belongs to. A string that
            is either '+junk' or the name of a Launchpad `IProduct`.
        :param branch: The name of the branch.
        """
        self._authserver = authserver
        self._owner = owner
        self._product = product
        self._name = name

    def checkPath(self, path_on_branch):
        """Raise an error if `path_on_branch` is not valid.

        This allows us to enforce a certain level of policy about what goes
        into a branch directory on Launchpad. Specifically, we do not allow
        arbitrary files at the top-level, we only allow Bazaar control
        directories, and backups of same.

        :raise PermissionDenied: if `path_on_branch` is forbidden.
        """
        if path_on_branch == '':
            return
        segments = get_path_segments(path_on_branch)
        if segments[0] not in ALLOWED_DIRECTORIES:
            raise PermissionDenied(
                FORBIDDEN_DIRECTORY_ERROR % (segments[0],))

    def create(self):
        """Create a branch in the database.

        :raise TransportNotPossible: If the branch owner or product does not
            exist.
        :raise PermissionDenied: If the branch cannot be created in the
            database. This might indicate that the branch already exists, or
            that its creation is forbidden by a policy.
        """
        deferred = self._authserver.createBranch(
            self._owner, self._product, self._name)

        def convert_fault(failure):
            failure.trap(Fault)
            fault = failure.value
            if fault.faultCode == NOT_FOUND_FAULT_CODE:
                # One might think that it would make sense to raise
                # NoSuchFile here, but that makes the client do "clever"
                # things like say "Parent directory of
                # bzr+ssh://bazaar.launchpad.dev/~noone/firefox/branch
                # does not exist.  You may supply --create-prefix to
                # create all leading parent directories."  Which is just
                # misleading.
                raise PermissionDenied(fault.faultString)
            elif fault.faultCode == PERMISSION_DENIED_FAULT_CODE:
                raise PermissionDenied(fault.faultString)
            else:
                raise

        return deferred.addErrback(convert_fault)

    def ensureUnderlyingPath(self, transport):
        """Ensure that the directory for the branch exists on the transport.
        """
        deferred = self.getRealPath('')
        deferred.addErrback(lambda failure: failure.trap(BranchNotFound))
        deferred.addCallback(
            lambda real_path: ensure_base(transport.clone(real_path)))
        return deferred

    def getRealPath(self, url_fragment_on_branch):
        """Return the 'real' URL-escaped path to a path within this branch.

        :param path_on_branch: A URL fragment referring to a path within this
             branch.

        :raise BranchNotFound: if the branch does not exist.
        :raise PermissionDenied: if `url_fragment_on_branch` is forbidden.

        :return: A path relative to the base directory where all branches
            are stored. This path will look like '00/AB/02/43/.bzr/foo', where
            'AB0243' is the database ID of the branch expressed in hex and
            '.bzr/foo' is `path_on_branch`.
        """
        try:
            self.checkPath(url_fragment_on_branch)
        except PermissionDenied:
            return defer.fail(failure.Failure())
        deferred = self.getID()
        return deferred.addCallback(
            lambda branch_id: '/'.join(
                [branch_id_to_path(branch_id), url_fragment_on_branch]))

    def getID(self):
        """Return the database ID of this branch.

        :raise BranchNotFound: if the branch does not exist.
        :return: the database ID of the branch, an integer.
        """
        return self._getInfo().addCallback(lambda branch_info: branch_info[0])

    def getPermissions(self):
        """Return the permissions that the current user has for this branch.

        :raise BranchNotFound: if the branch does not exist.
        :return: WRITABLE if the user can write to the branch, READ_ONLY
            otherwise.
        """
        return self._getInfo().addCallback(lambda branch_info: branch_info[1])

    def _getInfo(self):
        deferred = self._authserver.getBranchInformation(
            self._owner, self._product, self._name)
        def check_branch_id(branch_info):
            (branch_id, permissions) = branch_info
            if branch_id == '':
                raise BranchNotFound(
                    owner=self._owner, product=self._product, name=self._name)
            return branch_info
        return deferred.addCallback(check_branch_id)

    def requestMirror(self):
        """Request that the branch be mirrored as soon as possible.

        :raise BranchNotFound: if the branch does not exist.
        """
        deferred = self.getID()
        deferred.addCallback(self._authserver.requestMirror)
        return deferred


class _BaseLaunchpadServer(Server):
    """Bazaar Server for Launchpad branches.

    This server provides facilities for transports that use a virtual
    filesystem, backed by an XML-RPC server.

    For more information, see the module docstring.
    """

    def __init__(self, scheme, authserver, user_id):
        """Construct a LaunchpadServer.

        :param scheme: The URL scheme to use.
        :param authserver: An XML-RPC client that implements callRemote.
        :param user_id: The database ID for the user who is accessing
            branches.
        """
        # bzrlib's Server class does not have a constructor, so we cannot
        # safely upcall it.
        # pylint: disable-msg=W0231
        self._scheme = scheme
        self._authserver = CachingAuthserverClient(authserver, user_id)
        self._is_set_up = False

    def _buildControlDirectory(self, stack_on_url):
        """Return a MemoryTransport that has '.bzr/control.conf' in it."""
        memory_server = MemoryServer()
        memory_server.setUp()
        transport = get_transport(memory_server.get_url())
        if stack_on_url == '':
            return transport

        format = BzrDirFormat.get_default_format()
        format.initialize_on_transport(transport)
        # XXX: JonathanLange 2008-05-20 bug=232242: We should use the
        # higher-level bzrlib APIs to do this:
        # bzrdir.get_config().set_default_stack_on(). But those APIs aren't in
        # bzr mainline yet, so...
        transport.put_bytes(
            '.bzr/control.conf', 'default_stack_on=%s\n' % stack_on_url)
        return get_transport('readonly+' + transport.base)

    def _transportFactory(self, url):
        """Create a transport for this server pointing at `url`.

        Override this in subclasses.
        """
        raise NotImplementedError("Override this in subclasses.")

    def _getLaunchpadBranch(self, virtual_path):
        return LaunchpadBranch.from_virtual_path(
            self._authserver, virtual_path)

    def _getTransportForLaunchpadBranch(self, lp_branch):
        """Return the transport for accessing `lp_branch`."""
        raise NotImplementedError("Override this in subclasses.")

    def _parseProductControlDirectory(self, virtual_path):
        """Parse `virtual_path` and return a product and path in that product.

        If we can't parse `virtual_path`, raise `InvalidControlDirectory`.
        """
        segments = get_path_segments(virtual_path, 3)
        if len(segments) < 3:
            raise InvalidControlDirectory(virtual_path)
        user, product, control = segments[:3]
        if not user.startswith('~'):
            raise InvalidControlDirectory(virtual_path)
        if control != '.bzr':
            raise InvalidControlDirectory(virtual_path)
        return product, '/'.join([control] + segments[3:])

    def _translateControlPath(self, virtual_url_fragment):
        virtual_path = urlutils.unescape(virtual_url_fragment).encode('utf-8')
        product, path = self._parseProductControlDirectory(virtual_path)
        deferred = self._authserver.getDefaultStackedOnBranch(product)
        deferred.addCallback(self._buildControlDirectory)
        return deferred.addCallback(
            lambda transport: (transport, urlutils.escape(path)))

    def translateVirtualPath(self, virtual_url_fragment):
        """Translate 'virtual_url_fragment' into a transport and sub-fragment.

        :param virtual_url_fragment: A virtual URL fragment to be translated.

        :raise NotABranchPath: If `virtual_url_fragment` does not have at
            least a valid path to a branch.
        :raise BranchNotFound: If `virtual_path` looks like a path to a
            branch, but there is no branch in the database that matches.
        :raise NoSuchFile: If `virtual_path` is *inside* a non-existing
            branch.
        :raise PermissionDenied: if the path on the branch is forbidden.

        :return: (transport, path_on_transport)
        """
        try:
            lp_branch, path = self._getLaunchpadBranch(virtual_url_fragment)
        except NotABranchPath:
            fail = failure.Failure()
            deferred = defer.maybeDeferred(
                self._translateControlPath, virtual_url_fragment)
            deferred.addErrback(lambda ignored: fail)
            return deferred

        virtual_path_deferred = lp_branch.getRealPath(path)

        def branch_not_found(failure):
            failure.trap(BranchNotFound)
            if path == '':
                # We are trying to translate a branch path that doesn't exist.
                return failure
            else:
                # We are trying to translate a path within a branch that
                # doesn't exist.
                raise NoSuchFile(virtual_url_fragment)

        virtual_path_deferred.addErrback(branch_not_found)

        def get_transport(real_path):
            deferred = self._getTransportForLaunchpadBranch(lp_branch)
            deferred.addCallback(lambda transport: (transport, real_path))
            return deferred

        return virtual_path_deferred.addCallback(get_transport)

    def get_url(self):
        """Return the URL of this server."""
        return self._scheme

    def setUp(self):
        """See Server.setUp."""
        register_transport(self.get_url(), self._transportFactory)
        self._is_set_up = True

    def tearDown(self):
        """See Server.tearDown."""
        if not self._is_set_up:
            return
        self._is_set_up = False
        unregister_transport(self.get_url(), self._transportFactory)


class LaunchpadServer(_BaseLaunchpadServer):
    """The Server used for codehosting services.

    This server provides a VFS that backs onto two transports: a 'hosted'
    transport and a 'mirrored' transport. When users push up 'hosted'
    branches, the branches are written to the hosted transport. Similarly,
    whenever users access branches that they can write to, they are accessed
    from the hosted transport. The mirrored transport is used for branches
    that the user can only read.

    In addition to basic VFS operations, this server provides operations for
    creating a branch and requesting for a branch to be mirrored. The
    associated transport, `AsyncLaunchpadTransport`, has hooks in certain
    filesystem-level operations to trigger these.
    """

    def __init__(self, authserver, user_id, hosted_transport,
                 mirror_transport):
        scheme = 'lp-%d:///' % id(self)
        super(LaunchpadServer, self).__init__(scheme, authserver, user_id)
        self._hosted_transport = hosted_transport
        self._mirror_transport = get_transport(
            'readonly+' + mirror_transport.base)

    def _transportFactory(self, url):
        """Construct a transport for the given URL. Used by the registry."""
        assert url.startswith(self.get_url())
        return SynchronousAdapter(AsyncLaunchpadTransport(self, url))

    def _getTransportForPermissions(self, permissions, lp_branch):
        """Get the appropriate transport for `permissions` on `lp_branch`."""
        if permissions == READ_ONLY:
            return self._mirror_transport
        else:
            transport = self._hosted_transport
            deferred = lp_branch.ensureUnderlyingPath(transport)
            deferred.addCallback(lambda ignored: transport)
            return deferred

    def _getTransportForLaunchpadBranch(self, lp_branch):
        """Return the transport for accessing `lp_branch`."""
        permissions_deferred = lp_branch.getPermissions()
        return permissions_deferred.addCallback(
            self._getTransportForPermissions, lp_branch)

    def createBranch(self, virtual_url_fragment):
        """Make a new directory for the given virtual URL fragment.

        If `virtual_url_fragment` is a branch directory, create the branch in
        the database, then create a matching directory on the backing
        transport.

        :param virtual_url_fragment: A virtual path to be translated.

        :raise NotABranchPath: If `virtual_path` does not have at least a
            valid path to a branch.
        :raise TransportNotPossible: If the branch owner or product does not
            exist.
        :raise PermissionDenied: If the branch cannot be created in the
            database. This might indicate that the branch already exists, or
            that its creation is forbidden by a policy.
        """
        lp_branch, ignored = self._getLaunchpadBranch(virtual_url_fragment)
        deferred = lp_branch.create()

        def ensure_path(branch_id):
            deferred = lp_branch.ensureUnderlyingPath(self._hosted_transport)
            return deferred.addCallback(lambda ignored: branch_id)
        return deferred.addCallback(ensure_path)

    def requestMirror(self, virtual_url_fragment):
        """Mirror the branch that owns 'virtual_url_fragment'.

        :param virtual_path: A virtual URL fragment to be translated.

        :raise NotABranchPath: If `virtual_url_fragment` does not have at
            least a valid path to a branch.
        """
        lp_branch, ignored = self._getLaunchpadBranch(virtual_url_fragment)
        return lp_branch.requestMirror()


class LaunchpadInternalServer(_BaseLaunchpadServer):
    """Server for Launchpad internal services.

    This server provides access to a transport using the Launchpad virtual
    filesystem. Unlike the `LaunchpadServer`, it backs onto a single transport
    and doesn't do any permissions work.

    Intended for use with the branch puller and scanner.
    """

    def __init__(self, scheme, authserver, branch_transport):
        super(LaunchpadInternalServer, self).__init__(
            scheme, authserver, LAUNCHPAD_SERVICES)
        self._branch_transport = branch_transport

    def _getTransportForLaunchpadBranch(self, lp_branch):
        """Return the transport for accessing `lp_branch`."""
        deferred = lp_branch.ensureUnderlyingPath(self._branch_transport)
        # We try to make the branch's directory on the underlying transport.
        # If the transport is read-only, then we just continue silently.
        def if_not_readonly(failure):
            failure.trap(TransportNotPossible)
            return self._branch_transport
        deferred.addCallback(lambda ignored: self._branch_transport)
        deferred.addErrback(if_not_readonly)
        return deferred

    def _transportFactory(self, url):
        """Construct a transport for the given URL. Used by the registry."""
        assert url.startswith(self.get_url())
        return SynchronousAdapter(AsyncVirtualTransport(self, url))


def get_scanner_server():
    """Get a Launchpad internal server for scanning branches."""
    proxy = xmlrpclib.ServerProxy(config.codehosting.branchfs_endpoint)
    authserver = BlockingProxy(proxy)
    branch_transport = get_transport(
        'readonly+' + config.supermirror.warehouse_root_url)
    return LaunchpadInternalServer(
        'lp-mirrored:///', authserver, branch_transport)


class _MultiServer(Server):
    """Server that wraps around multiple servers."""

    def __init__(self, *servers):
        self._servers = servers

    def setUp(self):
        for server in self._servers:
            server.setUp()

    def tearDown(self):
        for server in reversed(self._servers):
            server.tearDown()


def get_puller_server():
    """Get a server for the Launchpad branch puller.

    The server wraps up two `LaunchpadInternalServer`s. One of them points to
    the hosted branch area and is read-only, the other points to the mirrored
    area and is read/write.
    """
    proxy = xmlrpclib.ServerProxy(config.codehosting.branchfs_endpoint)
    authserver = BlockingProxy(proxy)
    hosted_transport = get_readonly_transport(
        get_chrooted_transport(config.codehosting.branches_root))
    mirrored_transport = get_chrooted_transport(
        config.supermirror.branchesdest)
    hosted_server = LaunchpadInternalServer(
        'lp-hosted:///', authserver,
        get_readonly_transport(hosted_transport))
    mirrored_server = LaunchpadInternalServer(
        'lp-mirrored:///', authserver, mirrored_transport)
    return _MultiServer(hosted_server, mirrored_server)


class AsyncVirtualTransport(Transport):
    """A transport for a virtual file system.

    Assumes that it has a 'server' which implements 'translateVirtualPath'.
    This method is expected to take an absolute virtual path and translate it
    into a real transport and a path on that transport.
    """

    def __init__(self, server, url):
        self.server = server
        Transport.__init__(self, url)

    def external_url(self):
        # There's no real external URL to this transport. It's heavily
        # dependent on the process.
        raise InProcessTransport(self)

    def _abspath(self, relpath):
        """Return the absolute, escaped path to `relpath` without the schema.
        """
        return urlutils.joinpath(
            self.base[len(self.server.get_url())-1:], relpath)

    def _getUnderylingTransportAndPath(self, relpath):
        """Return the underlying transport and path for `relpath`."""
        virtual_url_fragment = self._abspath(relpath)
        return self.server.translateVirtualPath(virtual_url_fragment)

    def _call(self, method_name, relpath, *args, **kwargs):
        """Call a method on the backing transport, translating relative,
        virtual paths to filesystem paths.

        If 'relpath' translates to a path that we only have read-access to,
        then the method will be called on the backing transport decorated with
        'readonly+'.
        """
        def call_method((transport, path)):
            method = getattr(transport, method_name)
            return method(path, *args, **kwargs)

        def convert_not_enough_information(failure):
            failure.trap(NotEnoughInformation)
            raise NoSuchFile(failure.value.virtual_url_fragment)

        deferred = self._getUnderylingTransportAndPath(relpath)
        deferred.addCallback(call_method)
        deferred.addErrback(convert_not_enough_information)
        return deferred

    # Transport methods
    def abspath(self, relpath):
        return urlutils.join(self.base, relpath)

    def append_file(self, relpath, f, mode=None):
        return self._call('append_file', relpath, f, mode)

    def clone(self, relpath=None):
        if relpath is None:
            return self.__class__(self.server, self.base)
        else:
            return self.__class__(
                self.server, urlutils.join(self.base, relpath))

    def delete(self, relpath):
        return self._call('delete', relpath)

    def delete_tree(self, relpath):
        return self._call('delete_tree', relpath)

    def get(self, relpath):
        return self._call('get', relpath)

    def get_bytes(self, relpath):
        return self._call('get_bytes', relpath)

    def has(self, relpath):
        return self._call('has', relpath)

    def iter_files_recursive(self):
        deferred = self._getUnderylingTransportAndPath('.')
        def iter_files((transport, path)):
            return transport.clone(path).iter_files_recursive()
        deferred.addCallback(iter_files)
        return deferred

    def listable(self):
        deferred = self._getUnderylingTransportAndPath('.')
        def listable((transport, path)):
            return transport.listable()
        deferred.addCallback(listable)
        return deferred

    def list_dir(self, relpath):
        return self._call('list_dir', relpath)

    def lock_read(self, relpath):
        return self._call('lock_read', relpath)

    def lock_write(self, relpath):
        return self._call('lock_write', relpath)

    def mkdir(self, relpath, mode=None):
        return self._call('mkdir', relpath, mode)

    def open_write_stream(self, relpath, mode=None):
        return self._call('open_write_stream', relpath, mode)

    def put_file(self, relpath, f, mode=None):
        return self._call('put_file', relpath, f, mode)

    def local_realPath(self, relpath):
        # This method should return an absolute path (not URL) that points to
        # `relpath` and dereferences any symlinks. The absolute path should be
        # on this transport.
        #
        # Here, we assume that the underlying transport has no symlinks
        # (Bazaar transports cannot create symlinks). This means that we can
        # just return the absolute path.
        return self._abspath(relpath)

    def readv(self, relpath, offsets, adjust_for_latency=False,
              upper_limit=None):
        return self._call(
            'readv', relpath, offsets, adjust_for_latency, upper_limit)

    def rename(self, rel_from, rel_to):
        to_deferred = self._getUnderylingTransportAndPath(rel_to)
        from_deferred = self._getUnderylingTransportAndPath(rel_from)
        deferred = gatherResults([to_deferred, from_deferred])

        def check_transports_and_rename(
            ((to_transport, to_path), (from_transport, from_path))):
            if to_transport is not from_transport:
                raise TransportNotPossible(
                    'cannot move between underlying transports')
            return getattr(from_transport, 'rename')(from_path, to_path)

        deferred.addCallback(check_transports_and_rename)
        return deferred

    def rmdir(self, relpath):
        return self._call('rmdir', relpath)

    def stat(self, relpath):
        return self._call('stat', relpath)

    def writeChunk(self, relpath, offset, data):
        return self._call('writeChunk', relpath, offset, data)


class SynchronousAdapter(Transport):
    """Converts an asynchronous transport to a synchronous one."""

    def __init__(self, async_transport):
        self._async_transport = async_transport

    def _extractResult(self, deferred):
        failures = []
        successes = []
        deferred.addCallbacks(successes.append, failures.append)
        if len(failures) == 1:
            failures[0].raiseException()
        elif len(successes) == 1:
            return successes[0]
        else:
            raise AssertionError("%r has not fired yet." % (deferred,))

    @property
    def base(self):
        return self._async_transport.base

    def _abspath(self, relpath):
        return self._async_transport._abspath(relpath)

    def clone(self, offset=None):
        """See `bzrlib.transport.Transport`."""
        cloned_async = self._async_transport.clone(offset)
        return SynchronousAdapter(cloned_async)

    def external_url(self):
        """See `bzrlib.transport.Transport`."""
        raise InProcessTransport()

    def abspath(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._async_transport.abspath(relpath)

    def append_file(self, relpath, f, mode=None):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(
            self._async_transport.append_file(relpath, f, mode))

    def delete(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.delete(relpath))

    def delete_tree(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.delete_tree(relpath))

    def get(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.get(relpath))

    def get_bytes(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.get_bytes(relpath))

    def has(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.has(relpath))

    def iter_files_recursive(self):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(
            self._async_transport.iter_files_recursive())

    def listable(self):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.listable())

    def list_dir(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.list_dir(relpath))

    def lock_read(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.lock_read(relpath))

    def lock_write(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.lock_write(relpath))

    def mkdir(self, relpath, mode=None):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.mkdir(relpath, mode))

    def open_write_stream(self, relpath, mode=None):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(
            self._async_transport.open_write_stream(relpath, mode))

    def put_file(self, relpath, f, mode=None):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(
            self._async_transport.put_file(relpath, f, mode))

    def local_realPath(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(
            self._async_transport.local_realPath(relpath))

    def readv(self, relpath, offsets, adjust_for_latency=False,
              upper_limit=None):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(
            self._async_transport.readv(
                relpath, offsets, adjust_for_latency, upper_limit))

    def rename(self, rel_from, rel_to):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(
            self._async_transport.rename(rel_from, rel_to))

    def rmdir(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.rmdir(relpath))

    def stat(self, relpath):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(self._async_transport.stat(relpath))

    def writeChunk(self, relpath, offset, data):
        """See `bzrlib.transport.Transport`."""
        return self._extractResult(
            self._async_transport.writeChunk(relpath, offset, data))


class AsyncLaunchpadTransport(AsyncVirtualTransport):
    """Virtual transport to implement the Launchpad VFS for branches.

    This implements a few hooks to translate filesystem operations (such as
    making a certain kind of directory) into Launchpad operations (such as
    creating a branch in the database).

    It also converts the Launchpad-specific translation errors (such as 'not a
    valid branch path') into Bazaar errors (such as 'no such file').
    """

    def _getUnderylingTransportAndPath(self, relpath):
        """Return the underlying transport and path for `relpath`."""
        deferred = AsyncVirtualTransport._getUnderylingTransportAndPath(
            self, relpath)
        def convert_failure(failure):
            failure.trap(NotABranchPath)
            # If a virtual path doesn't point to a branch, then we cannot
            # translate it to an underlying transport. For almost all
            # purposes, this is as good as not existing at all.
            exception = failure.value
            raise NoSuchFile(
                exception.virtual_url_fragment, exception.reason)
        return deferred.addErrback(convert_failure)

    def mkdir(self, relpath, mode=None):
        # We hook into mkdir so that we can request the creation of a branch
        # and so that we can provide useful errors in the special case where
        # the user tries to make a directory like "~foo/bar". That is, a
        # directory that has too little information to be translated into a
        # Launchpad branch.
        deferred = AsyncVirtualTransport._getUnderylingTransportAndPath(
            self, relpath)
        def maybe_make_branch_in_db(failure):
            # Looks like we are trying to make a branch.
            failure.trap(BranchNotFound)
            return self.server.createBranch(self._abspath(relpath))
        def check_permission_denied(failure):
            # You can't ever create a directory that's not even a valid branch
            # name. That's strictly forbidden.
            failure.trap(NotABranchPath)
            exc_object = failure.value
            raise PermissionDenied(
                exc_object.virtual_url_fragment, exc_object.reason)
        def real_mkdir((transport, path)):
            return getattr(transport, 'mkdir')(path, mode)

        deferred.addCallback(real_mkdir)
        deferred.addErrback(maybe_make_branch_in_db)
        deferred.addErrback(check_permission_denied)
        return deferred

    def rename(self, rel_from, rel_to):
        # We hook into rename to catch the "unlock branch" event, so that we
        # can request a mirror once a branch is unlocked.
        abs_from = self._abspath(rel_from)
        if is_lock_directory(abs_from):
            deferred = self.server.requestMirror(abs_from)
        else:
            deferred = defer.succeed(None)
        deferred = deferred.addCallback(
            lambda ignored: AsyncVirtualTransport.rename(
                self, rel_from, rel_to))
        return deferred

    def rmdir(self, relpath):
        # We hook into rmdir in order to prevent users from deleting branches,
        # products and people from the VFS.
        virtual_url_fragment = self._abspath(relpath)
        path_segments = virtual_url_fragment.lstrip('/').split('/')
        if len(path_segments) <= 3:
            return defer.fail(
                failure.Failure(PermissionDenied(virtual_url_fragment)))
        return AsyncVirtualTransport.rmdir(self, relpath)
