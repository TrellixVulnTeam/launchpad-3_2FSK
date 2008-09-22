# Copyright 2004-2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0702,W0231

"""Transport utilities for the codehosting system.

The code hosting filesystem is implemented using Bazaar transports. This
module contains utilities for implementing virtual filesystem using
bzrlib.transport classes.
"""

__metaclass__ = type
__all__ = [
    'AsyncVirtualTransport',
    'get_chrooted_transport',
    'get_readonly_transport',
    '_MultiServer',
    'NotABranchPath',
    'NotEnoughInformation',
    'SynchronousAdapter',
    ]


from bzrlib.errors import (
    BzrError, InProcessTransport, NoSuchFile, TransportNotPossible)
from bzrlib import urlutils
from bzrlib.transport import (
    chroot, get_transport, Server, Transport)

from twisted.internet import defer

from canonical.twistedsupport import gatherResults


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


def get_chrooted_transport(url):
    """Return a chrooted transport serving `url`."""
    chroot_server = chroot.ChrootServer(get_transport(url))
    chroot_server.setUp()
    return get_transport(chroot_server.get_url())


def get_readonly_transport(transport):
    """Wrap `transport` in a readonly transport."""
    return get_transport('readonly+' + transport.base)


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
        return defer.succeed(self._abspath(relpath))

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
        raise InProcessTransport(self)

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
