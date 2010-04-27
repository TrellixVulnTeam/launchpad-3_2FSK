# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0213

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
them up.

This means our services must detect events like 'make directory' and 'unlock
branch' and translate them into Launchpad operations like 'create branch' and
'request mirror' before performing those operations.

So, we have a `LaunchpadServer` which implements the core operations --
translate a path, make a branch and request a mirror -- in terms of virtual
paths.

This server does most of its work by querying an XML-RPC server that provides
the `IBranchFileSystem` interface and passing what that returns to a
`ITransportDispatch` object.

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
    'BadUrl',
    'BadUrlLaunchpad',
    'BadUrlScheme',
    'BadUrlSsh',
    'branch_id_to_path',
    'BranchPolicy',
    'DirectDatabaseLaunchpadServer',
    'get_lp_server',
    'get_multi_server',
    'get_rw_server',
    'get_scanner_server',
    'make_branch_mirrorer',
    'LaunchpadInternalServer',
    'LaunchpadServer',
    ]

import xmlrpclib

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir, BzrDirFormat
from bzrlib.config import TransportConfig
from bzrlib.errors import (
    NoSuchFile, NotStacked, PermissionDenied, TransportNotPossible,
    UnstackableBranchFormat)
from bzrlib.plugins.loom.branch import LoomSupport
from bzrlib.smart.request import jail_info
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryServer
from bzrlib import urlutils

from lazr.uri import URI

from twisted.internet import defer
from twisted.python import failure, log

from zope.component import getUtility
from zope.interface import implements, Interface

from lp.codehosting.vfs.branchfsclient import (
    BlockingProxy, BranchFileSystemClient)
from lp.codehosting.vfs.transport import (
    AsyncVirtualServer, AsyncVirtualTransport, _MultiServer,
    get_chrooted_transport, get_readonly_transport, TranslationError)
from canonical.config import config
from canonical.launchpad.xmlrpc import faults
from lp.code.enums import BranchType
from lp.code.interfaces.branchlookup import IBranchLookup
from lp.code.interfaces.codehosting import (
    BRANCH_TRANSPORT, CONTROL_TRANSPORT, LAUNCHPAD_SERVICES)
from lp.services.twistedsupport.xmlrpc import trap_fault


class BadUrl(Exception):
    """Tried to access a branch from a bad URL."""


class BadUrlSsh(BadUrl):
    """Tried to access a branch from sftp or bzr+ssh."""


class BadUrlLaunchpad(BadUrl):
    """Tried to access a branch from launchpad.net."""


class BadUrlScheme(BadUrl):
    """Found a URL with an untrusted scheme."""

    def __init__(self, scheme, url):
        BadUrl.__init__(self, scheme, url)
        self.scheme = scheme


# The directories allowed directly beneath a branch directory. These are the
# directories that Bazaar creates as part of regular operation. We support
# only two numbered backups to avoid indefinite space usage.
ALLOWED_DIRECTORIES = ('.bzr', '.bzr.backup', 'backup.bzr', 'backup.bzr.~1~',
	'backup.bzr.~2~')
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


def branch_id_to_path(branch_id):
    """Convert the given branch ID into NN/NN/NN/NN form, where NN is a two
    digit hexadecimal number.

    Some filesystems are not capable of dealing with large numbers of inodes.
    The codehosting system has tens of thousands of branches and thus splits
    the branches into several directories. The Launchpad id is used in order
    to determine the splitting.
    """
    h = "%08x" % int(branch_id)
    return '%s/%s/%s/%s' % (h[:2], h[2:4], h[4:6], h[6:])


def get_path_segments(path, maximum_segments=-1):
    """Break up the given path into segments.

    If 'path' ends with a trailing slash, then the final empty segment is
    ignored.
    """
    return path.strip('/').split('/', maximum_segments)


def is_lock_directory(absolute_path):
    """Is 'absolute_path' a Bazaar branch lock directory?"""
    return absolute_path.endswith('/.bzr/branch/lock/held')


def get_scanner_server():
    """Get a Launchpad internal server for scanning branches."""
    proxy = xmlrpclib.ServerProxy(config.codehosting.codehosting_endpoint)
    codehosting_endpoint = BlockingProxy(proxy)
    branch_transport = get_readonly_transport(
        get_transport(config.codehosting.internal_branch_by_id_root))
    return LaunchpadInternalServer(
        'lp-mirrored:///', codehosting_endpoint, branch_transport)


def get_rw_server(direct_database=False):
    """Get a server that can write to the Launchpad branch vfs.

    You can only call this usefully on the codehost -- the transport this
    server provides are backed onto file:/// URLs.

    :param direct_database: if True, use a server implementation that talks
        directly to the database.  If False, the default, use a server
        implementation that talks to the internal XML-RPC server.
    """
    transport = get_chrooted_transport(
        config.codehosting.mirrored_branches_root, mkdir=True)
    if direct_database:
        return DirectDatabaseLaunchpadServer('lp-internal:///', transport)
    else:
        proxy = xmlrpclib.ServerProxy(config.codehosting.codehosting_endpoint)
        codehosting_endpoint = BlockingProxy(proxy)
        return LaunchpadInternalServer(
            'lp-internal:///', codehosting_endpoint, transport)


def get_multi_server(write_hosted=False, write_mirrored=False,
                     direct_database=False):
    """Get a server with access to both mirrored and hosted areas.

    The server wraps up two `LaunchpadInternalServer`s or
    `DirectDatabaseLaunchpadServer`s. One server points to the hosted branch
    area and the other points to the mirrored area.

    Write permision defaults to False, but can be overridden.

    :param write_hosted: if True, lp-hosted URLs are writeable.  Otherwise,
        they are read-only.
    :param write_mirrored: if True, lp-mirrored URLs are writeable.
        Otherwise, they are read-only.

    :param direct_database: if True, use a server implementation that talks
        directly to the database.  If False, the default, use a server
        implementation that talks to the internal XML-RPC server.
    """
    # XXX 2010-04-20, MichaelHudson: this function will disappear in a later
    # pipe.
    hosted_transport = get_chrooted_transport(
        config.codehosting.mirrored_branches_root, mkdir=True)
    if not write_hosted:
        hosted_transport = get_readonly_transport(hosted_transport)
    mirrored_transport = get_chrooted_transport(
        config.codehosting.mirrored_branches_root, mkdir=True)
    if not write_mirrored:
        mirrored_transport = get_readonly_transport(mirrored_transport)
    if direct_database:
        make_server = DirectDatabaseLaunchpadServer
    else:
        proxy = xmlrpclib.ServerProxy(config.codehosting.codehosting_endpoint)
        codehosting_endpoint = BlockingProxy(proxy)
        def make_server(scheme, transport):
            return LaunchpadInternalServer(
                scheme, codehosting_endpoint, transport)
    hosted_server = make_server('lp-hosted:///', hosted_transport)
    mirrored_server = make_server('lp-mirrored:///', mirrored_transport)
    return _MultiServer(hosted_server, mirrored_server)


class ITransportDispatch(Interface):
    """Turns descriptions of transports into transports."""

    def makeTransport(transport_tuple):
        """Return a transport and trailing path for 'transport_tuple'.

        :param transport_tuple: a tuple of (transport_type, transport_data,
            trailing_path), as returned by IBranchFileSystem['translatePath'].

        :return: A transport and a path on that transport that point to a
            place that matches the one described in transport_tuple.
        :rtype: (`bzrlib.transport.Transport`, str)
        """


class BranchTransportDispatch:
    """Turns BRANCH_TRANSPORT tuples into transports that point to branches.

    This transport dispatch knows how branches are laid out on the disk in a
    particular "area". It doesn't know anything about the "hosted" or
    "mirrored" areas.

    This is used directly by our internal services (puller and scanner).
    """
    implements(ITransportDispatch)

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

    def makeTransport(self, transport_tuple):
        """See `ITransportDispatch`.

        :raise PermissionDenied: If the path on the branch's transport is
            forbidden because it's not in ALLOWED_DIRECTORIES.
        """
        transport_type, data, trailing_path = transport_tuple
        if transport_type != BRANCH_TRANSPORT:
            raise UnknownTransportType(transport_type)
        self._checkPath(trailing_path)
        transport = self.base_transport.clone(branch_id_to_path(data['id']))
        try:
            transport.create_prefix()
        except TransportNotPossible:
            # Silently ignore TransportNotPossible. This is raised when the
            # base transport is read-only.
            pass
        return transport, trailing_path


class TransportDispatch:
    """Make transports for hosted branch areas and virtual control dirs.

    This transport dispatch knows about whether a particular branch should be
    served read-write or read-only. It also knows how to serve .bzr control
    directories for products (to enable default stacking).

    This is used for the rich codehosting VFS that we serve publically.
    """
    implements(ITransportDispatch)

    def __init__(self, rw_transport):
        self._rw_dispatch = BranchTransportDispatch(rw_transport)
        self._ro_dispatch = BranchTransportDispatch(
            get_readonly_transport(rw_transport))
        self._transport_factories = {
            BRANCH_TRANSPORT: self._makeBranchTransport,
            CONTROL_TRANSPORT: self._makeControlTransport,
            }

    def makeTransport(self, transport_tuple):
        transport_type, data, trailing_path = transport_tuple
        factory = self._transport_factories[transport_type]
        data['trailing_path'] = trailing_path
        return factory(**data), trailing_path

    def _makeBranchTransport(self, id, writable, trailing_path=''):
        if writable:
            dispatch = self._rw_dispatch
        else:
            dispatch = self._ro_dispatch
        transport, ignored = dispatch.makeTransport(
            (BRANCH_TRANSPORT, dict(id=id), trailing_path))
        return transport

    def _makeControlTransport(self, default_stack_on, trailing_path=None):
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
        memory_server.start_server()
        transport = get_transport(memory_server.get_url())
        if default_stack_on == '':
            return transport
        format = BzrDirFormat.get_default_format()
        bzrdir = format.initialize_on_transport(transport)
        bzrdir.get_config().set_default_stack_on(
            urlutils.unescape(default_stack_on))
        return get_readonly_transport(transport)


class _BaseLaunchpadServer(AsyncVirtualServer):
    """Bazaar `Server` for translating Lanuchpad paths via XML-RPC.

    This server provides facilities for transports that use a virtual
    filesystem, backed by an XML-RPC server.

    For more information, see the module docstring.

    :ivar _branchfs_client: An object that has a method 'translatePath' that
        returns a Deferred that fires information about how a path can be
        translated into a transport. See `IBranchFilesystem['translatePath']`.

    :ivar _transport_dispatch: An `ITransportDispatch` provider used to
        convert the data from the branchfs client into an actual transport and
        path on that transport.
    """

    def __init__(self, scheme, codehosting_api, user_id,
                 seen_new_branch_hook=None):
        """Construct a LaunchpadServer.

        :param scheme: The URL scheme to use.
        :param codehosting_api: An XML-RPC client that implements callRemote.
        :param user_id: The database ID for the user who is accessing
            branches.
        :param seen_new_branch_hook: A callable that will be called once for
            each branch accessed via this server.
        """
        AsyncVirtualServer.__init__(self, scheme)
        self._branchfs_client = BranchFileSystemClient(
            codehosting_api, user_id,
            seen_new_branch_hook=seen_new_branch_hook)
        self._is_start_server = False

    def translateVirtualPath(self, virtual_url_fragment):
        """See `AsyncVirtualServer.translateVirtualPath`.

        Call 'translatePath' on the branchfs client with the fragment and then
        use 'makeTransport' on the _transport_dispatch to translate that
        result into a transport and trailing path.
        """
        deferred = self._branchfs_client.translatePath(
            '/' + virtual_url_fragment)

        def path_not_translated(failure):
            trap_fault(
                failure, faults.PathTranslationError, faults.PermissionDenied)
            raise NoSuchFile(virtual_url_fragment)

        def unknown_transport_type(failure):
            failure.trap(UnknownTransportType)
            raise NoSuchFile(virtual_url_fragment)

        deferred.addCallbacks(
            self._transport_dispatch.makeTransport, path_not_translated)
        deferred.addErrback(unknown_transport_type)
        return deferred


class LaunchpadInternalServer(_BaseLaunchpadServer):
    """Server for Launchpad internal services.

    This server provides access to a transport using the Launchpad virtual
    filesystem. Unlike the `LaunchpadServer`, it backs onto a single transport
    and doesn't do any permissions work.

    Intended for use with the branch puller and scanner.
    """

    def __init__(self, scheme, codehosting_api, branch_transport):
        """Construct a `LaunchpadInternalServer`.

        :param scheme: The URL scheme to use.

        :param codehosting_api: An object that provides a 'translatePath'
            method.

        :param branch_transport: A Bazaar `Transport` that refers to an
            area where Launchpad branches are stored, generally either the
            hosted or mirrored areas.
        """
        super(LaunchpadInternalServer, self).__init__(
            scheme, codehosting_api, LAUNCHPAD_SERVICES)
        self._transport_dispatch = BranchTransportDispatch(branch_transport)

    def start_server(self):
        super(LaunchpadInternalServer, self).start_server()
        try:
            self._transport_dispatch.base_transport.ensure_base()
        except TransportNotPossible:
            pass

    def destroy(self):
        """Delete the on-disk branches and tear down."""
        self._transport_dispatch.base_transport.delete_tree('.')
        self.stop_server()


class DirectDatabaseLaunchpadServer(AsyncVirtualServer):

    def __init__(self, scheme, branch_transport):
        AsyncVirtualServer.__init__(self, scheme)
        self._transport_dispatch = BranchTransportDispatch(branch_transport)

    def start_server(self):
        super(DirectDatabaseLaunchpadServer, self).start_server()
        try:
            self._transport_dispatch.base_transport.ensure_base()
        except TransportNotPossible:
            pass

    def destroy(self):
        """Delete the on-disk branches and tear down."""
        self._transport_dispatch.base_transport.delete_tree('.')
        self.stop_server()

    def translateVirtualPath(self, virtual_url_fragment):
        """See `AsyncVirtualServer.translateVirtualPath`.

        This implementation connects to the database directly.
        """
        deferred = defer.succeed(
            getUtility(IBranchLookup).getIdAndTrailingPath(
                virtual_url_fragment))

        def process_result((branch_id, trailing)):
            if branch_id is None:
                raise NoSuchFile(virtual_url_fragment)
            else:
                return self._transport_dispatch.makeTransport(
                    (BRANCH_TRANSPORT, dict(id=branch_id), trailing[1:]))

        deferred.addCallback(process_result)
        return deferred


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
            deferred = self.server.branchChanged(abs_from)
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
        # XXX: JonathanLange 2008-11-19 bug=300551: This code assumes stuff
        # about the VFS! We need to figure out the best way to delegate the
        # decision about permission-to-delete to the XML-RPC server.
        if len(path_segments) <= 3:
            return defer.fail(
                failure.Failure(PermissionDenied(virtual_url_fragment)))
        return AsyncVirtualTransport.rmdir(self, relpath)


class LaunchpadServer(_BaseLaunchpadServer):
    """The Server used for the public SSH codehosting service.

    This server provides a VFS that backs onto a transport that stores
    branches by id.  The TransportDispatch object takes care of showing a
    writeable or read-only view of each branch as appropriate.

    In addition to basic VFS operations, this server provides operations for
    creating a branch and requesting for a branch to be mirrored. The
    associated transport, `AsyncLaunchpadTransport`, has hooks in certain
    filesystem-level operations to trigger these.
    """

    asyncTransportFactory = AsyncLaunchpadTransport

    def __init__(self, codehosting_api, user_id, branch_transport,
                 seen_new_branch_hook=None):
        """Construct a `LaunchpadServer`.

        See `_BaseLaunchpadServer` for more information.

        :param codehosting_api: An object that has 'createBranch' and
            'branchChanged' methods in addition to a 'translatePath' method.
            These methods should return Deferreds.
            XXX: JonathanLange 2008-11-19: Specify this interface better.
        :param user_id: The database ID of the user to connect as.
        :param branch_transport: A Bazaar `Transport` that points to the
            "hosted" area of Launchpad. See module docstring for more
            information.
        :param seen_new_branch_hook: A callable that will be called once for
            each branch accessed via this server.
        """
        scheme = 'lp-%d:///' % id(self)
        super(LaunchpadServer, self).__init__(
            scheme, codehosting_api, user_id, seen_new_branch_hook)
        self._transport_dispatch = TransportDispatch(branch_transport)

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
        deferred = self._branchfs_client.createBranch(virtual_url_fragment)

        def translate_fault(failure):
            # We turn faults.NotFound into a PermissionDenied, even
            # though one might think that it would make sense to raise
            # NoSuchFile. Sadly, raising that makes the client do "clever"
            # things like say "Parent directory of
            # bzr+ssh://bazaar.launchpad.dev/~noone/firefox/branch does not
            # exist. You may supply --create-prefix to create all leading
            # parent directories", which is just misleading.
            fault = trap_fault(
                failure, faults.NotFound, faults.PermissionDenied)
            faultString = fault.faultString
            if isinstance(faultString, unicode):
                faultString = faultString.encode('utf-8')
            raise PermissionDenied(virtual_url_fragment, faultString)

        return deferred.addErrback(translate_fault)

    def _normalize_stacked_on_url(self, branch):
        """Normalize and return the stacked-on location of `branch`.

        In the common case, `branch` will either be unstacked or stacked on a
        relative path, in which case this is very easy: just return the
        location.

        If `branch` is stacked on the absolute URL of another Launchpad
        branch, we normalize this to a relative path (mutating the branch) and
        return the relative path.

        If `branch` is stacked on some other absolute URL we don't recognise,
        we just return that and rely on the `branchChanged` XML-RPC method
        recording a complaint in the appropriate place.
        """
        stacked_on_url = get_stacked_on_url(branch)
        if stacked_on_url is None:
            return None
        if '://' not in stacked_on_url:
            # Assume it's a relative path.
            return stacked_on_url
        uri = URI(stacked_on_url)
        if uri.scheme not in ['http', 'bzr+ssh', 'sftp']:
            return stacked_on_url
        launchpad_domain = config.vhost.mainsite.hostname
        if not uri.underDomain(launchpad_domain):
            return stacked_on_url
        # We use TransportConfig directly because the branch
        # is still locked at this point!  We're effectively
        # 'borrowing' the lock that is being released.
        branch_config = TransportConfig(branch._transport, 'branch.conf')
        branch_config.set_option(uri.path, 'stacked_on_location')
        return uri.path

    def branchChanged(self, virtual_url_fragment):
        """Notify Launchpad of a change to the a branch.

        This method tries hard to not exit via an exception, because the
        client side experience is not good in that case.  Instead, log.err()
        is called, which will result in an OOPS being logged.

        :param virtual_url_fragment: A url fragment that points to a path
            owned by a branch.
        """
        deferred = self._branchfs_client.translatePath(
            '/' + virtual_url_fragment)

        def got_path_info((transport_type, data, trailing_path)):
            if transport_type != BRANCH_TRANSPORT:
                raise NotABranchPath(virtual_url_fragment)
            transport, _ = self._transport_dispatch.makeTransport(
                (transport_type, data, trailing_path))
            if jail_info.transports:
                jail_info.transports.append(transport)
            try:
                branch = BzrDir.open_from_transport(transport).open_branch(
                    ignore_fallbacks=True)
                last_revision = branch.last_revision()
                stacked_on_url = self._normalize_stacked_on_url(branch)
                # XXX: Aaron Bentley 2008-06-13
                # Bazaar does not provide a public API for learning about
                # format markers.  Fix this in Bazaar, then here.
                control_string = branch.bzrdir._format.get_format_string()
                branch_string = branch._format.get_format_string()
                repository_string = \
                    branch.repository._format.get_format_string()
            finally:
                if jail_info.transports:
                    jail_info.transports.remove(transport)
            if stacked_on_url is None:
                stacked_on_url = ''
            return self._branchfs_client.branchChanged(
                data['id'], stacked_on_url, last_revision,
                control_string, branch_string, repository_string)

        # It gets really confusing if we raise an exception from this method
        # (the branch remains locked, but this isn't obvious to the client) so
        # just log the error, which will result in an OOPS being logged.
        return deferred.addCallback(got_path_info).addErrback(log.err)


def get_lp_server(user_id, codehosting_endpoint_url=None, branch_directory=None,
                  seen_new_branch_hook=None):
    """Create a Launchpad server.

    :param user_id: A unique database ID of the user whose branches are
        being served.
    :param codehosting_endpoint_url: URL for the branch file system end-point.
    :param hosted_directory: Where the branches are uploaded to.
    :param mirror_directory: Where all Launchpad branches are mirrored.
    :param seen_new_branch_hook:
    :return: A `LaunchpadServer`.
    """
    # Get the defaults from the config.
    if codehosting_endpoint_url is None:
        codehosting_endpoint_url = config.codehosting.codehosting_endpoint
    if branch_directory is None:
        branch_directory = config.codehosting.mirrored_branches_root

    branch_url = urlutils.local_path_to_url(branch_directory)
    codehosting_client = xmlrpclib.ServerProxy(codehosting_endpoint_url)
    branch_transport = get_chrooted_transport(branch_url)
    lp_server = LaunchpadServer(
        BlockingProxy(codehosting_client), user_id, branch_transport,
        seen_new_branch_hook)
    return lp_server


def get_stacked_on_url(branch):
    """Get the stacked-on URL for 'branch', or `None` if not stacked."""
    try:
        return branch.get_stacked_on_url()
    except (NotStacked, UnstackableBranchFormat):
        return None


class BranchPolicy:
    """Policy on how to mirror branches.

    In particular, a policy determines which branches are safe to mirror by
    checking their URLs and deciding whether or not to follow branch
    references. A policy also determines how the mirrors of branches should be
    stacked.
    """

    def createDestinationBranch(self, source_branch, destination_url):
        """Create a destination branch for 'source_branch'.

        Creates a branch at 'destination_url' that is has the same format as
        'source_branch'.  Any content already at 'destination_url' will be
        deleted.  Generally the new branch will have no revisions, but they
        will be copied for import branches, because this can be done safely
        and efficiently with a vfs-level copy (see `ImportedBranchPolicy`,
        below).

        :param source_branch: The Bazaar branch that will be mirrored.
        :param destination_url: The place to make the destination branch. This
            URL must point to a writable location.
        :return: The destination branch.
        """
        dest_transport = get_transport(destination_url)
        if dest_transport.has('.'):
            dest_transport.delete_tree('.')
        if isinstance(source_branch, LoomSupport):
            # Looms suck.
            revision_id = None
        else:
            revision_id = 'null:'
        source_branch.bzrdir.clone_on_transport(
            dest_transport, revision_id=revision_id)
        return Branch.open(destination_url)

    def getStackedOnURLForDestinationBranch(self, source_branch,
                                            destination_url):
        """Get the stacked on URL for `source_branch`.

        In particular, the URL it should be stacked on when it is mirrored to
        `destination_url`.
        """
        return None

    def shouldFollowReferences(self):
        """Whether we traverse references when mirroring.

        Subclasses must override this method.

        If we encounter a branch reference and this returns false, an error is
        raised.

        :returns: A boolean to indicate whether to follow a branch reference.
        """
        raise NotImplementedError(self.shouldFollowReferences)

    def transformFallbackLocation(self, branch, url):
        """Validate, maybe modify, 'url' to be used as a stacked-on location.

        :param branch:  The branch that is being opened.
        :param url: The URL that the branch provides for its stacked-on
            location.
        :return: (new_url, check) where 'new_url' is the URL of the branch to
            actually open and 'check' is true if 'new_url' needs to be
            validated by checkAndFollowBranchReference.
        """
        raise NotImplementedError(self.transformFallbackLocation)

    def checkOneURL(self, url):
        """Check the safety of the source URL.

        Subclasses must override this method.

        :param url: The source URL to check.
        :raise BadUrl: subclasses are expected to raise this or a subclass
            when it finds a URL it deems to be unsafe.
        """
        raise NotImplementedError(self.checkOneURL)


class MirroredBranchPolicy(BranchPolicy):
    """Mirroring policy for MIRRORED branches.

    In summary:

     - follow references,
     - only open non-Launchpad http: and https: URLs.
    """

    def __init__(self, stacked_on_url=None):
        self.stacked_on_url = stacked_on_url

    def getStackedOnURLForDestinationBranch(self, source_branch,
                                            destination_url):
        """See `BranchPolicy.getStackedOnURLForDestinationBranch`.

        Mirrored branches are stacked on the default stacked-on branch of
        their product, except when we're mirroring the default stacked-on
        branch itself.
        """
        if self.stacked_on_url is None:
            return None
        stacked_on_url = urlutils.join(destination_url, self.stacked_on_url)
        if destination_url == stacked_on_url:
            return None
        return self.stacked_on_url

    def shouldFollowReferences(self):
        """See `BranchPolicy.shouldFollowReferences`.

        We traverse branch references for MIRRORED branches because they
        provide a useful redirection mechanism and we want to be consistent
        with the bzr command line.
        """
        return True

    def transformFallbackLocation(self, branch, url):
        """See `BranchPolicy.transformFallbackLocation`.

        For mirrored branches, we stack on whatever the remote branch claims
        to stack on, but this URL still needs to be checked.
        """
        return urlutils.join(branch.base, url), True

    def checkOneURL(self, url):
        """See `BranchPolicy.checkOneURL`.

        We refuse to mirror from Launchpad or a ssh-like or file URL.
        """
        # Avoid circular import
        from lp.code.interfaces.branch import get_blacklisted_hostnames
        uri = URI(url)
        launchpad_domain = config.vhost.mainsite.hostname
        if uri.underDomain(launchpad_domain):
            raise BadUrlLaunchpad(url)
        for hostname in get_blacklisted_hostnames():
            if uri.underDomain(hostname):
                raise BadUrl(url)
        if uri.scheme in ['sftp', 'bzr+ssh']:
            raise BadUrlSsh(url)
        elif uri.scheme not in ['http', 'https']:
            raise BadUrlScheme(uri.scheme, url)


class ImportedBranchPolicy(BranchPolicy):
    """Mirroring policy for IMPORTED branches.

    In summary:

     - don't follow references,
     - assert the URLs start with the prefix we expect for imported branches.
    """

    def createDestinationBranch(self, source_branch, destination_url):
        """See `BranchPolicy.createDestinationBranch`.

        Because we control the process that creates import branches, a
        vfs-level copy is safe and more efficient than a bzr fetch.
        """
        source_transport = source_branch.bzrdir.root_transport
        dest_transport = get_transport(destination_url)
        while True:
            # We loop until the remote file list before and after the copy is
            # the same to catch the case where the remote side is being
            # mutated as we copy it.
            if dest_transport.has('.'):
                dest_transport.delete_tree('.')
            files_before = set(source_transport.iter_files_recursive())
            source_transport.copy_tree_to_transport(dest_transport)
            files_after = set(source_transport.iter_files_recursive())
            if files_before == files_after:
                break
        return Branch.open_from_transport(dest_transport)

    def shouldFollowReferences(self):
        """See `BranchPolicy.shouldFollowReferences`.

        We do not traverse references for IMPORTED branches because the
        code-import system should never produce branch references.
        """
        return False

    def transformFallbackLocation(self, branch, url):
        """See `BranchPolicy.transformFallbackLocation`.

        Import branches should not be stacked, ever.
        """
        raise AssertionError("Import branch unexpectedly stacked!")

    def checkOneURL(self, url):
        """See `BranchPolicy.checkOneURL`.

        If the URL we are mirroring from does not start how we expect the pull
        URLs of import branches to start, something has gone badly wrong, so
        we raise AssertionError if that's happened.
        """
        if not url.startswith(config.launchpad.bzr_imports_root_url):
            raise AssertionError(
                "Bogus URL for imported branch: %r" % url)


def make_branch_mirrorer(branch_type, protocol=None,
                         mirror_stacked_on_url=None):
    """Create a `BranchMirrorer` with the appropriate `BranchPolicy`.

    :param branch_type: A `BranchType` to select a policy by.
    :param protocol: Optional protocol for the mirrorer to work with.
        If given, its log will also be used.
    :param mirror_stacked_on_url: For mirrored branches, the default URL
        to stack on.  Ignored for other branch types.
    :return: A `BranchMirrorer`.
    """
    # Avoid circular import
    from lp.codehosting.puller.worker import BranchMirrorer

    if branch_type == BranchType.MIRRORED:
        policy = MirroredBranchPolicy(mirror_stacked_on_url)
    elif branch_type == BranchType.IMPORTED:
        policy = ImportedBranchPolicy()
    else:
        raise AssertionError(
            "Unexpected branch type: %r" % branch_type)

    if protocol is not None:
        log_function = protocol.log
    else:
        log_function = None

    return BranchMirrorer(policy, protocol, log_function)
