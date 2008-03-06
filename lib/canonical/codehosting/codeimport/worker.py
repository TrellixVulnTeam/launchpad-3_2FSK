# Copyright 2008 Canonical Ltd.  All rights reserved.

"""The code import worker. This imports code from foreign repositories."""

__metaclass__ = type
__all__ = [
    'BazaarBranchStore',
    'ForeignTreeStore',
    'get_default_bazaar_branch_store',
    'get_default_foreign_tree_store']


import logging
import os
import shutil
import tempfile

from zope.component import getUtility

from bzrlib.branch import Branch
from bzrlib.builtins import _create_prefix as create_prefix
from bzrlib.bzrdir import BzrDir
from bzrlib.transport import get_transport
from bzrlib.errors import NoSuchFile, NotBranchError
from bzrlib.osutils import pumpfile
from bzrlib.urlutils import join as urljoin

from canonical.codehosting.codeimport.foreigntree import (
    CVSWorkingTree, SubversionWorkingTree)
from canonical.codehosting.codeimport.tarball import (
    create_tarball, extract_tarball)
from canonical.config import config
from canonical.launchpad.interfaces import (
    BranchType, BranchTypeError, ICodeImportJobSet, RevisionControlSystems)

from cscvs.cmds import totla
import cscvs
import CVS
import SCM


def ensure_base(transport):
    """Make sure that the base directory of `transport` exists.

    If the base directory does not exist, try to make it. If the parent of the
    base directory doesn't exist, try to make that, and so on.
    """
    try:
        transport.ensure_base()
    except NoSuchFile:
        create_prefix(transport)


class BazaarBranchStore:
    """A place where Bazaar branches of code imports are kept."""

    # This code is intended to replace c.codehosting.codeimport.publish and
    # canonical.codeimport.codeimport.gettarget.

    def __init__(self, transport):
        """Construct a Bazaar branch store based at `transport`."""
        self.transport = transport

    def _checkBranchIsImported(self, db_branch):
        """Raise `BranchTypeError` if `db_branch` not an imported branch."""
        if db_branch.branch_type != BranchType.IMPORTED:
            raise BranchTypeError(
                "Can only store imported branches: %r is of type %r."
                % (db_branch, db_branch.branch_type))

    def _getMirrorURL(self, db_branch):
        """Return the URL that `db_branch` is stored at."""
        return urljoin(self.transport.base, '%08x' % db_branch.id)

    def pull(self, db_branch, target_path):
        """Pull down the Bazaar branch for `code_import` to `target_path`.

        :return: A Bazaar working tree for the branch of `code_import`.
        """
        self._checkBranchIsImported(db_branch)
        try:
            bzr_dir = BzrDir.open(self._getMirrorURL(db_branch))
        except NotBranchError:
            return BzrDir.create_standalone_workingtree(target_path)
        bzr_dir.sprout(target_path)
        return BzrDir.open(target_path).open_workingtree()

    def push(self, db_branch, bzr_tree):
        """Push up `bzr_tree` as the Bazaar branch for `code_import`."""
        self._checkBranchIsImported(db_branch)
        ensure_base(self.transport)
        branch_from = bzr_tree.branch
        target_url = self._getMirrorURL(db_branch)
        try:
            branch_to = Branch.open(target_url)
        except NotBranchError:
            branch_to = BzrDir.create_branch_and_repo(target_url)
        branch_to.pull(branch_from)


def get_default_bazaar_branch_store():
    """Return the default `BazaarBranchStore`."""
    return BazaarBranchStore(
        get_transport(config.codeimport.bazaar_branch_store))


def _download(transport, relpath, local_path):
    """Download the file at `relpath` from `transport` to `local_path`."""
    local_file = open(local_path, 'wb')
    try:
        remote_file = transport.get(relpath)
        try:
            pumpfile(remote_file, local_file)
        finally:
            remote_file.close()
    finally:
        local_file.close()


class ForeignTreeStore:
    """Manages retrieving and storing foreign working trees.

    The code import system stores tarballs of CVS and SVN working trees on
    another system. The tarballs are kept in predictable locations based on
    the ID of their `CodeImport`.

    The tarballs are all kept in one directory. The filename of a tarball is
    XXXXXXXX.tar.gz, where 'XXXXXXXX' is the ID of the `CodeImport` in hex.
    """

    def __init__(self, transport):
        """Construct a `ForeignTreeStore`.

        :param transport: A writable transport that points to the base
            directory where the tarballs are stored.
        :ptype transport: `bzrlib.transport.Transport`.
        """
        self.transport = transport

    def _getForeignTree(self, code_import, target_path):
        """Return a foreign tree object for `code_import`."""
        if code_import.rcs_type == RevisionControlSystems.SVN:
            return SubversionWorkingTree(
                str(code_import.svn_branch_url), str(target_path))
        elif code_import.rcs_type == RevisionControlSystems.CVS:
            return CVSWorkingTree(
                str(code_import.cvs_root), str(code_import.cvs_module),
                target_path)
        else:
            raise AssertionError(
                "%r has an unknown RCS type: %r" %
                (code_import, code_import.rcs_type))

    def _getTarballName(self, code_import):
        """Return the name of the tarball for the code import."""
        return '%08x.tar.gz' % code_import.branch.id

    def archive(self, code_import, foreign_tree):
        """Archive the foreign tree."""
        tarball_name = self._getTarballName(code_import)
        create_tarball(foreign_tree.local_path, tarball_name)
        tarball = open(tarball_name, 'rb')
        ensure_base(self.transport)
        try:
            self.transport.put_file(tarball_name, tarball)
        finally:
            tarball.close()

    def fetch(self, code_import, target_path):
        """Fetch the foreign branch for `code_import` to `target_path`.

        If there is no tarball archived for `code_import`, then try to
        download (i.e. checkout) the foreign tree from its source repository,
        generally on a third party server.
        """
        try:
            return self.fetchFromArchive(code_import, target_path)
        except NoSuchFile:
            return self.fetchFromSource(code_import, target_path)

    def fetchFromSource(self, code_import, target_path):
        """Fetch the foreign tree for `code_import` to `target_path`."""
        branch = self._getForeignTree(code_import, target_path)
        branch.checkout()
        return branch

    def fetchFromArchive(self, code_import, target_path):
        """Fetch the foreign tree for `code_import` from the archive."""
        tarball_name = self._getTarballName(code_import)
        if not self.transport.has(tarball_name):
            raise NoSuchFile(tarball_name)
        _download(self.transport, tarball_name, tarball_name)
        extract_tarball(tarball_name, target_path)
        tree = self._getForeignTree(code_import, target_path)
        tree.update()
        return tree


def get_default_foreign_tree_store():
    """Get the default `ForeignTreeStore`."""
    return ForeignTreeStore(
        get_transport(config.codeimport.foreign_tree_store))


class ImportWorker:
    """Oversees the actual work of a code import."""

    # Where the Bazaar working tree will be stored.
    BZR_WORKING_TREE_PATH = 'bzr_working_tree'

    # Where the foreign working tree will be stored.
    FOREIGN_WORKING_TREE_PATH = 'foreign_working_tree'

    def __init__(self, job_id, foreign_tree_store, bazaar_branch_store,
                 logger):
        """Construct an `ImportWorker`.

        :param job_id: The database ID of the `CodeImportJob` to run.
        :param foreign_tree_store: A `ForeignTreeStore`. The import worker
            uses this to fetch and store foreign branches.
        :param bazaar_branch_store: A `BazaarBranchStore`. The import worker
            uses this to fetch and store the Bazaar branches that are created
            and updated during the import process.
        :param logger: A Logger to pass to cscvs.
        """
        self.job = getUtility(ICodeImportJobSet).getById(job_id)
        self.foreign_tree_store = foreign_tree_store
        self.bazaar_branch_store = bazaar_branch_store
        self.working_directory = tempfile.mkdtemp()
        self._foreign_branch = None
        self._logger = logger
        self._bazaar_working_tree_path = os.path.join(
            self.working_directory, self.BZR_WORKING_TREE_PATH)
        self._foreign_working_tree_path = os.path.join(
            self.working_directory, self.FOREIGN_WORKING_TREE_PATH)

    def getBazaarWorkingTree(self):
        """Return the Bazaar `WorkingTree` that we are importing into."""
        if os.path.isdir(self._bazaar_working_tree_path):
            shutil.rmtree(self._bazaar_working_tree_path)
        return self.bazaar_branch_store.pull(
            self.job.code_import.branch, self._bazaar_working_tree_path)

    def getForeignTree(self):
        """Return the foreign branch object that we are importing from.

        :return: A `SubversionWorkingTree` or a `CVSWorkingTree`.
        """
        if os.path.isdir(self._foreign_working_tree_path):
            shutil.rmtree(self._foreign_working_tree_path)
        os.mkdir(self._foreign_working_tree_path)
        return self.foreign_tree_store.fetch(
            self.job.code_import, self._foreign_working_tree_path)

    def importToBazaar(self, foreign_tree, bazaar_tree):
        """Actually import `foreign_tree` into `bazaar_tree`.

        :param foreign_tree: A `SubversionWorkingTree` or a `CVSWorkingTree`.
        :param bazaar_tree: A `bzrlib.workingtree.WorkingTree`.
        """
        foreign_directory = foreign_tree.local_path
        bzr_directory = str(bazaar_tree.basedir)

        scm_branch = SCM.branch(bzr_directory)
        last_commit = cscvs.findLastCscvsCommit(scm_branch)

        # If branch in `bazaar_tree` doesn't have any identifiable CSCVS
        # revisions, CSCVS "initialises" the branch.
        if last_commit is None:
            self._runToBaz(
                foreign_directory, "-SI", "MAIN.1", bzr_directory)

        # Now we synchronise the branch, that is, import all new revisions
        # from the foreign branch into the Bazaar branch. If we've just
        # initialized the Bazaar branch, then this means we import *all*
        # revisions.
        last_commit = cscvs.findLastCscvsCommit(scm_branch)
        self._runToBaz(
            foreign_directory, "-SC", "%s::" % last_commit, bzr_directory)

    def _runToBaz(self, source_dir, flags, revisions, bazpath):
        """Actually run the CSCVS utility that imports revisions.

        :param source_dir: The directory containing the foreign working tree
            that we are importing from.
        :param flags: Flags to pass to `totla.totla`.
        :param revisions: The revisions to import.
        :param bazpath: The directory containing the Bazaar working tree that
            we are importing into.
        """
        # XXX: JonathanLange 2008-02-08: We need better documentation for
        # `flags` and `revisions`.
        config = CVS.Config(source_dir)
        config.args = ["--strict", "-b", bazpath,
                       flags, revisions, bazpath]
        totla.totla(config, self._logger, config.args, SCM.tree(source_dir))

    def run(self):
        """Run the code import job.

        This is the primary public interface to the `ImportWorker`. This
        method:

         1. Retrieves an up-to-date foreign tree to import.
         2. Gets the Bazaar branch to import into.
         3. Imports the foreign tree into the Bazaar branch. If we've
            already imported this before, we synchronize the imported Bazaar
            branch with the latest changes to the foreign tree.
         4. Publishes the newly-updated Bazaar branch, making it available to
            Launchpad users.
         5. Archives the foreign tree, so that we can update it quickly next
            time.
        """
        foreign_tree = self.getForeignTree()
        bazaar_tree = self.getBazaarWorkingTree()
        self.importToBazaar(foreign_tree, bazaar_tree)
        self.bazaar_branch_store.push(
            self.job.code_import.branch, bazaar_tree)
        self.foreign_tree_store.archive(
            self.job.code_import, foreign_tree)
        shutil.rmtree(bazaar_tree.basedir)
        shutil.rmtree(foreign_tree.local_path)
