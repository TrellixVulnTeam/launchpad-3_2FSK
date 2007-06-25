# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""Bazaar transport for the Launchpad code hosting file system."""

__metaclass__ = type
__all__ = ['branch_id_to_path', 'LaunchpadServer', 'LaunchpadTransport',
           'UntranslatablePath']

from bzrlib.errors import BzrError, NoSuchFile, TransportNotPossible
from bzrlib import urlutils
from bzrlib.transport import (
    get_transport,
    register_transport,
    Server,
    Transport,
    unregister_transport,
    )

from canonical.authserver.interfaces import READ_ONLY


def branch_id_to_path(branch_id):
    """Convert the given branch ID into NN/NN/NN/NN form, where NN is a two
    digit hexadecimal number.
    """
    h = "%08x" % int(branch_id)
    return '%s/%s/%s/%s' % (h[:2], h[2:4], h[4:6], h[6:])


def split_with_padding(a_string, splitter, num_fields, padding=None):
    """Split the given string into exactly num_fields.

    If the given string doesn't have enough tokens to split into num_fields
    fields, then the resulting list of tokens is padded with 'padding'.
    """
    tokens = a_string.split(splitter, num_fields - 1)
    tokens.extend([padding] * max(0, num_fields - len(tokens)))
    return tokens


# XXX: JonathanLange 2007-06-13, This should probably be part of bzrlib.
# See https://launchpad.net/bugs/120135.
def makedirs(base_transport, path, mode=None):
    """Create 'path' on 'base_transport', even if parents of 'path' don't exist
    yet.
    """
    need_to_create = []
    transport = base_transport.clone(path)
    while True:
        try:
            transport.mkdir('.', mode)
        except NoSuchFile:
            need_to_create.append(transport)
        else:
            break
        transport = transport.clone('..')
    while need_to_create:
        transport = need_to_create.pop()
        transport.mkdir('.', mode)


def get_path_segments(path):
    return path.lstrip('/').split('/')


class UntranslatablePath(BzrError):

    _fmt = ("Could not translate %(path)s onto backing transport for "
            "user %(user)r")


class LaunchpadServer(Server):
    """Bazaar Server for Launchpad branches.

    See LaunchpadTransport for more information.
    """

    def __init__(self, authserver, user_id, hosting_transport,
                 mirror_transport):
        """
        Construct a LaunchpadServer.

        :param authserver: An xmlrpclib.ServerProxy that points to the
            authserver.
        :param user_id: A login ID for the user who is accessing branches.
        :param hosting_transport: A Transport pointing to the root of where the
            branches are actually stored.
        :param mirror_transport: A Transport pointing to the root of where
            branches are mirrored to.
        """
        self.authserver = authserver
        self.user_dict = self.authserver.getUser(user_id)
        self.user_id = self.user_dict['id']
        self.user_name = self.user_dict['name']
        self.backing_transport = hosting_transport
        self.mirror_transport = get_transport(
            'readonly+' + mirror_transport.base)
        self._is_set_up = False

    def dirty(self, virtual_path):
        """Mark the branch containing virtual_path as dirty."""
        # XXX: JonathanLange 2007-06-18, Note that we only mark branches as
        # dirty if they end up calling VFS (i.e. Transport) methods. If a
        # client does a writing smart operation that doesn't use VFS, we won't
        # catch it. (e.g. Branch.set_last_revision). This problem will become
        # more severe in Bazaar 0.18 and later.
        #
        # Instead we should register our own smart request handlers to override
        # the builtin ones.
        #
        # See https://launchpad.net/bugs/120949.
        branch_id, ignored, path = self._translate_path(virtual_path)
        self._dirty_branch_ids.add(branch_id)

    def mkdir(self, virtual_path):
        """Make a new directory for the given virtual path.

        If the request is to make a user or a product directory, fail with
        NoSuchFile error. If the request is to make a branch directory, create
        the branch in the database then create a matching directory on the
        backing transport.
        """
        path_segments = get_path_segments(virtual_path)
        if len(path_segments) != 3:
            raise NoSuchFile(virtual_path)
        branch_id = self._make_branch(*path_segments)
        makedirs(self.backing_transport, branch_id_to_path(branch_id))

    def _make_branch(self, user, product, branch):
        """Create a branch in the database for the given user and product.

        :param user: The loginID of the user who owns the new branch.
        :param product: The name of the product to which the new branch
            belongs.
        :param branch: The name of the new branch.

        :raise TransportNotPossible: If 'user' doesn't begin with a '~'.
        :raise NoSuchFile: If 'product' is not the name of an existing
            product.
        :return: The database ID of the new branch.
        """
        if not user.startswith('~'):
            raise TransportNotPossible(
                'Path must start with user or team directory: %r' % (user,))
        user = user[1:]
        user_dict = self.authserver.getUser(user)
        if not user_dict:
            raise NoSuchFile("%s doesn't exist" % (user,))
        user_id = user_dict['id']
        # If product is '+junk', then product_id should be '', which is
        # XML-RPC's way of saying None.
        if product == '+junk':
            if user_id == self.user_id:
                product_id = ''
            else:
                # XXX: JonathanLange 2007-06-04, This should perhaps be
                # 'PermissionDenied', not 'NoSuchFile'. However bzrlib doesn't
                # translate PermissionDenied errors. See _translate_error in
                # bzrlib/transport/remote.py.
                # See Launchpad bug 118736.
                raise NoSuchFile(
                    "+junk is only allowed under user directories, not team "
                    "directories.")
        else:
            product_id = self.authserver.fetchProductID(product)
            if not product_id:
                # XXX: JonathanLange 2007-06-04, This should perhaps be
                # 'PermissionDenied', not 'NoSuchFile'. However bzrlib doesn't
                # translate PermissionDenied errors. See _translate_error in
                # bzrlib/transport/remote.py.
                raise NoSuchFile(
                    "Directories directly under a user directory must be "
                    "named after a product name registered in Launchpad "
                    "<https://launchpad.net/>.")
        return self.authserver.createBranch(user_id, product_id, branch)

    def _translate_path(self, virtual_path):
        """Translate a virtual path into an internal branch id, permissions and
        relative path.

        'virtual_path' is a path that points to a branch or a path within a
        branch. This method returns the id of the branch, the permissions that
        the user running the server has for that branch and the path relative
        to that branch. In short, everything you need to be able to access a
        file in a branch.
        """
        # We can safely pad with '' because we can guarantee that no product or
        # branch name is the empty string. (Mapping '' to '+junk' happens
        # in _iter_branches). 'user' is checked later.
        user_dir, product, branch, path = split_with_padding(
            virtual_path.lstrip('/'), '/', 4, padding='')
        if not user_dir.startswith('~'):
            raise TransportNotPossible(
                'Path must start with user or team directory: %r'
                % (user_dir,))
        user = user_dir[1:]
        branch_id, permissions = self.authserver.getBranchInformation(
            self.user_id, user, product, branch)
        return branch_id, permissions, path

    def translate_virtual_path(self, virtual_path):
        """Translate an absolute virtual path into the real path on the backing
        transport.

        :raise UntranslatablePath: If path is untranslatable. This could be
            because the path is too short (doesn't include user, product and
            branch), or because the user, product or branch in the path don't
            exist.

        :raise TransportNotPossible: If the path is necessarily invalid. Most
            likely because it didn't begin with a tilde ('~').

        :return: The equivalent real path on the backing transport.
        """
        # XXX: JonathanLange 2007-05-29, We could differentiate between
        # 'branch not found' and 'not enough information in path to figure out
        # a branch'.
        branch_id, permissions, path = self._translate_path(virtual_path)
        if branch_id == '':
            raise UntranslatablePath(path=virtual_path, user=self.user_name)
        return '/'.join([branch_id_to_path(branch_id), path]), permissions

    def _factory(self, url):
        """Construct a transport for the given URL. Used by the registry."""
        assert url.startswith(self.scheme)
        return LaunchpadTransport(self, url)

    def get_url(self):
        """Return the URL of this server.

        The URL is of the form 'lp-<object_id>:///', where 'object_id' is
        id(self). This ensures that we can have LaunchpadServer objects for
        different users, different backing transports and, theoretically,
        different authservers.

        See Server.get_url.
        """
        return self.scheme

    def setUp(self):
        """See Server.setUp."""
        self.scheme = 'lp-%d:///' % id(self)
        self._dirty_branch_ids = set()
        register_transport(self.scheme, self._factory)
        self._is_set_up = True

    def tearDown(self):
        """See Server.tearDown."""
        if not self._is_set_up:
            return
        self._is_set_up = False
        for branch_id in self._dirty_branch_ids:
            self.authserver.requestMirror(branch_id)
        self._dirty_branch_ids = None
        unregister_transport(self.scheme, self._factory)


class LaunchpadTransport(Transport):
    """Transport to map from ~user/product/branch paths to codehosting paths.

    Launchpad serves its branches from URLs that look like
    bzr+ssh://launchpad/~user/product/branch. On the filesystem, the branches
    are stored by their id.

    This transport maps from the external, 'virtual' paths to the internal
    filesystem paths. The internal filesystem is represented by a backing
    transport.
    """

    def __init__(self, server, url):
        self.server = server
        Transport.__init__(self, url)

    def _abspath(self, relpath):
        """Return the absolute path to `relpath` without the schema."""
        return urlutils.joinpath(self.base[len(self.server.scheme)-1:],
                                 relpath)

    def _call(self, methodname, relpath, *args, **kwargs):
        """Call a method on the backing transport, translating relative,
        virtual paths to filesystem paths.

        If 'relpath' translates to a path that we only have read-access to,
        then the method will be called on the backing transport decorated with
        'readonly+'.

        :raise NoSuchFile: If the path cannot be translated.
        :raise TransportNotPossible: If trying to do a write operation on a
            read-only path.
        """
        path, permissions = self._translate_virtual_path(relpath)
        if permissions == READ_ONLY:
            transport = self.server.mirror_transport
        else:
            transport = self.server.backing_transport
        method = getattr(transport, methodname)
        return method(path, *args, **kwargs)

    def _writing_call(self, methodname, relpath, *args, **kwargs):
        """As for _call but mark the branch being written to as dirty."""
        result = self._call(methodname, relpath, *args, **kwargs)
        self.server.dirty(self._abspath(relpath))
        return result

    def _translate_virtual_path(self, relpath):
        """Translate a virtual path into a path on the backing transport.

        :raise NoSuchFile: If there is not way to map the given relpath to the
            backing transport.

        :return: A valid path on the backing transport.
        """
        try:
            return self.server.translate_virtual_path(self._abspath(relpath))
        except (UntranslatablePath, TransportNotPossible):
            raise NoSuchFile(relpath)

    # Transport methods
    def abspath(self, relpath):
        return urlutils.join(self.server.scheme, relpath)

    def append_file(self, relpath, f, mode=None):
        return self._writing_call('append_file', relpath, f, mode)

    def clone(self, relpath):
        return LaunchpadTransport(
            self.server, urlutils.join(self.base, relpath))

    def delete(self, relpath):
        return self._writing_call('delete', relpath)

    def delete_tree(self, relpath):
        return self._writing_call('delete_tree', relpath)

    def get(self, relpath):
        return self._call('get', relpath)

    def has(self, relpath):
        return self._call('has', relpath)

    def iter_files_recursive(self):
        path, ignored = self._translate_virtual_path('.')
        backing_transport = self.server.backing_transport.clone(path)
        return backing_transport.iter_files_recursive()

    def listable(self):
        return self.server.backing_transport.listable()

    def list_dir(self, relpath):
        return self._call('list_dir', relpath)

    def lock_read(self, relpath):
        return self._call('lock_read', relpath)

    def lock_write(self, relpath):
        return self._writing_call('lock_write', relpath)

    def mkdir(self, relpath, mode=None):
        # If we can't translate the path, then perhaps we are being asked to
        # create a new branch directory. Delegate to the server, as it knows
        # how to deal with absolute virtual paths.
        abspath = self._abspath(relpath)
        segments = get_path_segments(abspath)
        if len(segments) == 4 and segments[-1] != '.bzr':
            raise NoSuchFile(path=relpath,
                             extra=("Can only create .bzr directories "
                                    "directly beneath branch directories."))
        try:
            return self._writing_call('mkdir', relpath, mode)
        except NoSuchFile:
            return self.server.mkdir(abspath)

    def put_file(self, relpath, f, mode=None):
        return self._writing_call('put_file', relpath, f, mode)

    def rename(self, rel_from, rel_to):
        path, permissions = self._translate_virtual_path(rel_to)
        if permissions == READ_ONLY:
            raise TransportNotPossible('readonly transport')
        return self._writing_call('rename', rel_from, path)

    def rmdir(self, relpath):
        virtual_path = self._abspath(relpath)
        path_segments = path = virtual_path.lstrip('/').split('/')
        if len(path_segments) <= 3:
            raise NoSuchFile(virtual_path)
        return self._writing_call('rmdir', relpath)

    def stat(self, relpath):
        return self._call('stat', relpath)
