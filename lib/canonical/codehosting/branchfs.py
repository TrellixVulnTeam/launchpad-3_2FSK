# Copyright 2004-2008 Canonical Ltd.  All rights reserved.

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
talks to the database.

We hook the `LaunchpadServer` into Bazaar by implementing a
`AsyncVirtualTransport`, a `bzrlib.transport.Transport` that wraps all of its
operations so that they are translated by an object that implements
`translateVirtualPath`.  See transport.py for more information.

This virtual transport isn't quite enough, since it only does dumb path
translation. We also need to be able to interpret filesystem events in terms
of Launchpad branches. To do this, we provide a `LaunchpadTransport` that
hooks into operations like `mkdir` and ask the `LaunchpadServer` to make a
branch if appropriate.
"""


__metaclass__ = type
__all__ = [
    'AsyncLaunchpadTransport',
    'get_puller_server',
    'get_scanner_server',
    'LaunchpadInternalServer',
    'LaunchpadServer',
    ]

import xmlrpclib

from bzrlib.bzrdir import BzrDirFormat
from bzrlib.errors import (
    NoSuchFile, PermissionDenied, TransportNotPossible)
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryServer

from twisted.internet import defer
from twisted.python import failure

from canonical.codehosting import branch_id_to_path
from canonical.codehosting.branchfsclient import (
    BlockingProxy, CachingAuthserverClient, trap_fault)
from canonical.codehosting.bzrutils import ensure_base
from canonical.codehosting.transport import (
    AsyncVirtualServer, AsyncVirtualTransport, _MultiServer,
    get_chrooted_transport, get_readonly_transport, TranslationError)
from canonical.config import config
from canonical.launchpad.interfaces.codehosting import (
    BRANCH_TRANSPORT, CONTROL_TRANSPORT, LAUNCHPAD_SERVICES,
    NOT_FOUND_FAULT_CODE, PERMISSION_DENIED_FAULT_CODE)
from canonical.launchpad.xmlrpc import faults


# The directories allowed directly beneath a branch directory. These are the
# directories that Bazaar creates as part of regular operation.
ALLOWED_DIRECTORIES = ('.bzr', '.bzr.backup', 'backup.bzr')
FORBIDDEN_DIRECTORY_ERROR = (
    "Cannot create '%s'. Only Bazaar branches are allowed.")


class NotABranchPath(TranslationError):
    """Raised when we cannot translate a virtual URL fragment to a branch.

    In particular, this is raised when there is some intrinsic deficiency in
    the path itself.
    """

    _fmt = ("Could not translate %(virtual_url_fragment)r to branch. "
            "%(reason)s")


class UnknownTransportType(Exception):
    """Raised when we don't know the transport type."""


def get_path_segments(path, maximum_segments=-1):
    """Break up the given path into segments.

    If 'path' ends with a trailing slash, then the final empty segment is
    ignored.
    """
    return path.strip('/').split('/', maximum_segments)


def is_lock_directory(absolute_path):
    """Is 'absolute_path' a Bazaar branch lock directory?"""
    return absolute_path.endswith('/.bzr/branch/lock/held')


class SimpleTransportDispatch:

    def __init__(self, base_transport):
        self.base_transport = base_transport

    def _checkPath(self, path_on_branch):
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

    def make_transport(self, transport_tuple):
        transport_type, data, trailing_path = transport_tuple
        if transport_type != BRANCH_TRANSPORT:
            raise UnknownTransportType(transport_type)
        self._checkPath(trailing_path)
        transport = self.base_transport.clone(branch_id_to_path(data['id']))
        try:
            ensure_base(transport)
        except TransportNotPossible:
            # For now, silently ignore TransportNotPossible. This is raised
            # when transport is read-only. In the future, we probably want to
            # pass only writable transports in here: not sure.
            # XXX JonathanLange
            pass
        return transport, trailing_path


class TransportDispatch:

    def __init__(self, hosted_transport, mirrored_transport):
        self._hosted_dispatch = SimpleTransportDispatch(hosted_transport)
        self._mirrored_dispatch = SimpleTransportDispatch(mirrored_transport)
        self._transport_factories = {
            BRANCH_TRANSPORT: self.make_branch_transport,
            CONTROL_TRANSPORT: self.make_control_transport,
            }

    def make_transport(self, transport_tuple):
        transport_type, data, trailing_path = transport_tuple
        factory = self._transport_factories[transport_type]
        data['trailing_path'] = trailing_path
        return factory(**data), trailing_path

    def make_branch_transport(self, id, writable, trailing_path=''):
        if writable:
            dispatch = self._hosted_dispatch
        else:
            dispatch = self._mirrored_dispatch
        transport, ignored = dispatch.make_transport(
            (BRANCH_TRANSPORT, dict(id=id), trailing_path))
        if not writable:
            transport = get_transport('readonly+' + transport.base)
        return transport

    def make_control_transport(self, default_stack_on, trailing_path=None):
        """Make a transport that points to a control directory.

        A control directory is a .bzr directory containing a 'control.conf'
        file. This is used to specify configuration for branches created
        underneath the directory that contains the control directory.

        :param default_stack_on: The default stacked-on branch URL for
            branches that respect this control directory. If empty, then
            we'll return an empty memory transport.
        :return: A read-only `MemoryTransport` containing a working BzrDir,
            configured to use the given default stacked-on location.
        """
        memory_server = MemoryServer()
        memory_server.setUp()
        transport = get_transport(memory_server.get_url())
        if default_stack_on == '':
            return transport
        format = BzrDirFormat.get_default_format()
        bzrdir = format.initialize_on_transport(transport)
        bzrdir.get_config().set_default_stack_on(default_stack_on)
        return get_transport('readonly+' + transport.base)


class _BaseLaunchpadServer(AsyncVirtualServer):
    """Bazaar `Server` for translating Lanuchpad paths via XML-RPC.

    This server provides facilities for transports that use a virtual
    filesystem, backed by an XML-RPC server.

    For more information, see the module docstring.

    :ivar _authserver: An object that has a method 'translatePath' that
        returns a Deferred that fires information about how a path can be
        translated into a transport.

    :ivar _transport_dispatch: An object has a method 'make_transport' that
        takes the successful output of '_authserver.translatePath' and returns
        a tuple (transport, trailing_path)
    """

    def __init__(self, scheme, authserver, user_id):
        """Construct a LaunchpadServer.

        :param scheme: The URL scheme to use.
        :param authserver: An XML-RPC client that implements callRemote.
        :param user_id: The database ID for the user who is accessing
            branches.
        """
        AsyncVirtualServer.__init__(self, scheme)
        self._authserver = CachingAuthserverClient(authserver, user_id)
        self._is_set_up = False

    def translateVirtualPath(self, virtual_url_fragment):
        """See `AsyncVirtualServer.translateVirtualPath`.

        Call 'translatePath' on the authserver with the fragment and then use
        'make_transport' on the _transport_dispatch to translate that result
        into a transport and trailing path.
        """
        deferred = self._authserver.translatePath('/' + virtual_url_fragment)

        def path_not_translated(failure):
            trap_fault(failure, faults.PathTranslationError.error_code)
            raise NoSuchFile(virtual_url_fragment)

        return deferred.addCallbacks(
            self._transport_dispatch.make_transport, path_not_translated)


class LaunchpadServer(_BaseLaunchpadServer):
    """The Server used for the public SSH codehosting service.

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
        self.asyncTransportFactory = AsyncLaunchpadTransport
        self._hosted_transport = hosted_transport
        self._mirror_transport = get_transport(
            'readonly+' + mirror_transport.base)
        self._transport_dispatch = TransportDispatch(
            self._hosted_transport, self._mirror_transport)

    def createBranch(self, virtual_url_fragment):
        """Make a new directory for the given virtual URL fragment.

        If `virtual_url_fragment` is a branch directory, create the branch in
        the database, then create a matching directory on the backing
        transport.

        :param virtual_url_fragment: A virtual path to be translated.

        :raise NotABranchPath: If `virtual_path` does not have at least a
            valid path to a branch.
        :raise NotEnoughInformation: If `virtual_path` does not map to a
            branch.
        :raise PermissionDenied: If the branch cannot be created in the
            database. This might indicate that the branch already exists, or
            that its creation is forbidden by a policy.
        :raise Fault: If the XML-RPC server raises errors.
        """
        deferred = self._authserver.createBranch(virtual_url_fragment)

        def translate_fault(failure):
            # One might think that it would make sense to raise NoSuchFile
            # here, but that makes the client do "clever" things like say
            # "Parent directory of
            # bzr+ssh://bazaar.launchpad.dev/~noone/firefox/branch does not
            # exist. You may supply --create-prefix to create all leading
            # parent directories." Which is just misleading.
            fault = trap_fault(
                failure, NOT_FOUND_FAULT_CODE, PERMISSION_DENIED_FAULT_CODE)
            raise PermissionDenied(fault.faultString)

        return deferred.addErrback(translate_fault)

    def requestMirror(self, virtual_url_fragment):
        """Mirror the branch that owns 'virtual_url_fragment'.

        :param virtual_path: A virtual URL fragment to be translated.

        :raise NotABranchPath: If `virtual_url_fragment` points to a path
            that's not a branch.
        :raise NotEnoughInformation: If `virtual_url_fragment` cannot be
            translated to a branch.
        :raise Fault: If the XML-RPC server raises errors.
        """
        deferred = self._authserver.translatePath('/' + virtual_url_fragment)

        def got_path_info((transport_type, data, trailing_path)):
            if transport_type != BRANCH_TRANSPORT:
                raise NotABranchPath(virtual_url_fragment)
            return self._authserver.requestMirror(data['id'])

        return deferred.addCallback(got_path_info)


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
        self._transport_dispatch = SimpleTransportDispatch(
            self._branch_transport)


def get_scanner_server():
    """Get a Launchpad internal server for scanning branches."""
    proxy = xmlrpclib.ServerProxy(config.codehosting.branchfs_endpoint)
    authserver = BlockingProxy(proxy)
    branch_transport = get_transport(
        'readonly+' + config.supermirror.warehouse_root_url)
    return LaunchpadInternalServer(
        'lp-mirrored:///', authserver, branch_transport)


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


class AsyncLaunchpadTransport(AsyncVirtualTransport):
    """Virtual transport to implement the Launchpad VFS for branches.

    This implements a few hooks to translate filesystem operations (such as
    making a certain kind of directory) into Launchpad operations (such as
    creating a branch in the database).

    It also converts the Launchpad-specific translation errors (such as 'not a
    valid branch path') into Bazaar errors (such as 'no such file').
    """

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
            failure.trap(NoSuchFile)
            return self.server.createBranch(self._abspath(relpath))
        def real_mkdir((transport, path)):
            return getattr(transport, 'mkdir')(path, mode)

        deferred.addCallback(real_mkdir)
        deferred.addErrback(maybe_make_branch_in_db)
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
