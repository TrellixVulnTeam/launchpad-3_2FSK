# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tools for maintaining the Launchpad source code."""

__metaclass__ = type
__all__ = [
    'interpret_config',
    'parse_config_file',
    'plan_update',
    ]

import os
import shutil
import sys

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import BzrError
from bzrlib.plugin import load_plugins
from bzrlib.trace import report_exception
from bzrlib.transport import get_transport
from bzrlib.workingtree import WorkingTree


def parse_config_file(file_handle):
    """Parse the source code config file 'file_handle'.

    :param file_handle: A file-like object containing sourcecode
        configuration.
    :return: A sequence of lines of either '[key, value]' or
        '[key, value, optional]'.
    """
    for line in file_handle:
        if line.startswith('#'):
            continue
        yield [token.strip() for token in line.split('=')]


def interpret_config_entry(entry):
    """Interpret a single parsed line from the config file."""
    return (entry[0], (entry[1], len(entry) > 2))


def interpret_config(config_entries):
    """Interpret a configuration stream, as parsed by 'parse_config_file'.

    :param configuration: A sequence of parsed configuration entries.
    :return: A dict mapping the names of the sourcecode dependencies to a
        2-tuple of their branches and whether or not they are optional.
    """
    return dict(map(interpret_config_entry, config_entries))


def _subset_dict(d, keys):
    """Return a dict that's a subset of 'd', based on the keys in 'keys'."""
    return dict((key, d[key]) for key in keys)


def plan_update(existing_branches, configuration):
    """Plan the update to existing branches based on 'configuration'.

    :param existing_branches: A sequence of branches that already exist.
    :param configuration: A dictionary of sourcecode configuration, such as is
        returned by `interpret_config`.
    :return: (new_branches, update_branches, removed_branches), where
        'new_branches' are the branches in the configuration that don't exist
        yet, 'update_branches' are the branches in the configuration that do
        exist, and 'removed_branches' are the branches that exist locally, but
        not in the configuration. 'new_branches' and 'update_branches' are
        dicts of the same form as 'configuration', 'removed_branches' is a
        set of the same form as 'existing_branches'.
    """
    existing_branches = set(existing_branches)
    config_branches = set(configuration.keys())
    new_branches = config_branches - existing_branches
    removed_branches = existing_branches - config_branches
    update_branches = config_branches.intersection(existing_branches)
    return (
        _subset_dict(configuration, new_branches),
        _subset_dict(configuration, update_branches),
        removed_branches)


def find_branches(directory):
    """List the directory names in 'directory' that are branches."""
    transport = get_transport(directory)
    return (
        os.path.basename(branch.base.rstrip('/'))
        for branch in BzrDir.find_branches(transport))


def get_branches(sourcecode_directory, new_branches,
                 possible_transports=None):
    """Get the new branches into sourcecode."""
    for project, (branch_url, optional) in new_branches.iteritems():
        destination = os.path.join(sourcecode_directory, project)
        remote_branch = Branch.open(
            branch_url, possible_transports=possible_transports)
        possible_transports.append(
            remote_branch.bzrdir.root_transport)
        print 'Getting %s from %s' % (project, branch_url)
        # If the 'optional' flag is set, then it's a branch that shares
        # history with Launchpad, so we should share repositories. Otherwise,
        # we should avoid sharing repositories to avoid format
        # incompatibilities.
        force_new_repo = not optional
        try:
            remote_branch.bzrdir.sprout(
                destination, create_tree_if_local=True,
                source_branch=remote_branch, force_new_repo=force_new_repo,
                possible_transports=possible_transports)
        except BzrError:
            if optional:
                report_exception(sys.exc_info(), sys.stderr)
            else:
                raise


def update_branches(sourcecode_directory, update_branches,
                    possible_transports=None):
    """Update the existing branches in sourcecode."""
    if possible_transports is None:
        possible_transports = []
    # XXX: JonathanLange 2009-11-09: Rather than updating one branch after
    # another, we could instead try to get them in parallel.
    for project, (branch_url, optional) in update_branches.iteritems():
        destination = os.path.join(sourcecode_directory, project)
        print 'Updating %s' % (project,)
        local_tree = WorkingTree.open(destination)
        remote_branch = Branch.open(
            branch_url, possible_transports=possible_transports)
        possible_transports.append(
            remote_branch.bzrdir.root_transport)
        try:
            local_tree.pull(
                remote_branch, overwrite=True,
                possible_transports=possible_transports)
        except BzrError:
            if optional:
                report_exception(sys.exc_info(), sys.stderr)
            else:
                raise


def remove_branches(sourcecode_directory, removed_branches):
    """Remove sourcecode that's no longer there."""
    for project in removed_branches:
        destination = os.path.join(sourcecode_directory, project)
        print 'Removing %s' % project
        try:
            shutil.rmtree(destination)
        except OSError:
            os.unlink(destination)


def update_sourcecode(sourcecode_directory, config_filename):
    """Update the sourcecode."""
    config_file = open(config_filename)
    config = interpret_config(parse_config_file(config_file))
    config_file.close()
    branches = find_branches(sourcecode_directory)
    new, updated, removed = plan_update(branches, config)
    possible_transports = []
    get_branches(sourcecode_directory, new, possible_transports)
    update_branches(sourcecode_directory, updated, possible_transports)
    remove_branches(sourcecode_directory, removed)


def get_launchpad_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


# XXX: JonathanLange 2009-09-11: By default, the script will operate on the
# current checkout. Most people only have symlinks to sourcecode in their
# checkouts. This is fine for updating, but breaks for removing (you can't
# shutil.rmtree a symlink) and breaks for adding, since it adds the new branch
# to the checkout, rather than to the shared sourcecode area. Ideally, the
# script would see that the sourcecode directory is full of symlinks and then
# follow these symlinks to find the shared source directory. If the symlinks
# differ from each other (because of developers fiddling with things), we can
# take a survey of all of them, and choose the most popular.


def main(args):
    root = get_launchpad_root()
    if len(args) > 1:
        sourcecode_directory = args[1]
    else:
        sourcecode_directory = os.path.join(root, 'sourcecode')
    if len(args) > 2:
        config_filename = args[2]
    else:
        config_filename = os.path.join(root, 'utilities', 'sourcedeps.conf')
    print 'Sourcecode: %s' % (sourcecode_directory,)
    print 'Config: %s' % (config_filename,)
    load_plugins()
    update_sourcecode(sourcecode_directory, config_filename)
    return 0
