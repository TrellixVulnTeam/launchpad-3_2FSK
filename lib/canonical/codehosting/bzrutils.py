# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Utilities for dealing with Bazaar.

Everything in here should be submitted upstream.
"""

__metaclass__ = type
__all__ = [
    'get_branch_stacked_on_url',
    'ensure_base',
    'HttpAsLocalTransport',
    ]

from bzrlib.builtins import _create_prefix as create_prefix
from bzrlib import config
from bzrlib.errors import NoSuchFile, NotStacked, UnstackableBranchFormat
from bzrlib.transport import register_transport, unregister_transport
from bzrlib.transport.local import LocalTransport

from canonical.launchpad.webapp.uri import URI


def get_branch_stacked_on_url(a_bzrdir):
    """Return the stacked-on URL for the branch in this bzrdir.

    This method lets you figure out the stacked-on URL of a branch without
    opening the stacked-on branch. This lets us check for pathologically
    stacked branches.

    :raises NotBranchError: If there is no Branch.
    :raises NotStacked: If the Branch is not stacked.
    :raises UnstackableBranchFormat: If the Branch is of an unstackable
        format.
    :return: the stacked-on URL for the branch in this bzrdir.
    """
    # XXX: JonathanLange 2008-09-04: In a better world, this method would live
    # on BzrDir. Unfortunately, Bazaar lacks the configuration APIs to make
    # this possible (see below). Alternatively, Bazaar could provide us with a
    # way to open a Branch without opening the stacked-on branch.

    # XXX: JonathanLange 2008-09-04: In Bazaar 1.6, there's no generic way to
    # get the format of a branch from a BzrDir. Here, we just assume that if
    # you can't get the branch format using the newer API (i.e.
    # BzrDir.find_branch_format()), then the branch is not stackable.
    find_branch_format = getattr(a_bzrdir, 'find_branch_format', None)
    if find_branch_format is None:
        raise UnstackableBranchFormat(
            a_bzrdir._format, a_bzrdir.root_transport.base)
    format = find_branch_format()
    branch_transport = a_bzrdir.get_branch_transport(None)
    # XXX: JonathanLange 2008-09-04: We should be using BranchConfig here, but
    # that requires opening the Branch. Bazaar should grow APIs to let us
    # safely access the branch configuration without opening the branch. Here
    # we read the 'branch.conf' and don't bother with the locations.conf or
    # bazaar.conf. This is OK for Launchpad since we don't ever want to have
    # local client configuration. It's not OK for Bazaar in general.
    branch_config = config.TransportConfig(
        branch_transport, 'branch.conf')
    stacked_on_url = branch_config.get_option('stacked_on_location')
    if not stacked_on_url:
        raise NotStacked(a_bzrdir.root_transport.base)
    return stacked_on_url


# XXX: JonathanLange 2007-06-13 bugs=120135:
# This should probably be part of bzrlib.
def ensure_base(transport):
    """Make sure that the base directory of `transport` exists.

    If the base directory does not exist, try to make it. If the parent of the
    base directory doesn't exist, try to make that, and so on.
    """
    try:
        transport.ensure_base()
    except NoSuchFile:
        create_prefix(transport)


class HttpAsLocalTransport(LocalTransport):
    """A LocalTransport that works using http URLs.

    We have this because the Launchpad database has constraints on URLs for
    branches, disallowing file:/// URLs. bzrlib itself disallows
    file://localhost/ URLs.
    """

    def __init__(self, http_url):
        file_url = URI(
            scheme='file', host='', path=URI(http_url).path)
        return super(HttpAsLocalTransport, self).__init__(
            str(file_url))

    @classmethod
    def register(cls):
        """Register this transport."""
        register_transport('http://', cls)

    @classmethod
    def unregister(cls):
        """Unregister this transport."""
        unregister_transport('http://', cls)
