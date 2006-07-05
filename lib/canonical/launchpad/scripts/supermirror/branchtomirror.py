# Copyright 2006 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import httplib
import os
import shutil
import socket
import urllib2

import bzrlib.branch
import bzrlib.errors
from bzrlib.revision import NULL_REVISION


__all__ = ['BranchToMirror']

def identical_formats(branch_one, branch_two):
    """Check if two branches have the same bzrdir, repo, and branch formats."""
    # XXX AndrewBennetts 2006-05-18: comparing format objects is ugly.
    # See bug 45277.
    b1, b2 = branch_one, branch_two
    return (
        b1.bzrdir._format.__class__ == b2.bzrdir._format.__class__ and 
        b1.repository._format.__class__ == b2.repository._format.__class__ and
        b1._format.__class__ == b2._format.__class__
    )


class BranchToMirror:
    """This class represents a single branch that needs mirroring.

    It has a source URL, a destination URL, a database id and a 
    status client which is used to report on the mirror progress.
    """

    def __init__(self, src, dest, branch_status_client, branch_id):
        self.source = src
        self.dest = dest
        self.branch_status_client = branch_status_client
        self.branch_id = branch_id
        self._source_branch = None
        self._dest_branch = None
        assert self.dest is not None
        assert self.source is not None

    def _openSourceBranch(self):
        """Open the branch to pull from, useful to override in tests."""
        self._source_branch = bzrlib.branch.Branch.open(self.source)

    def _mirrorToDestBranch(self):
        """Open the branch to pull to, creating a new one if necessary.
        
        Useful to override in tests.
        """
        try:
            branch = bzrlib.bzrdir.BzrDir.open(self.dest).open_branch()
        except bzrlib.errors.NotBranchError:
            # Make a new branch in the same format as the source branch.
            branch = self._createDestBranch()
        else:
            # Check that destination branch is in the same format as the source.
            if identical_formats(self._source_branch, branch):
                # The destination exists, and is in the same format.  So all we
                # need to do is pull the new revisions.
                branch.pull(self._source_branch, overwrite=True)
            else:
                # The destination is in a different format to the source, so
                # we'll delete it and mirror from scratch.
                shutil.rmtree(self.dest)
                branch = self._createDestBranch()
        self._dest_branch = branch

    def _createDestBranch(self):
        """Create the branch to pull to, and copy the source's contents."""
        # XXX AndrewBennetts 2006-05-26:
        #    sprout builds a working tree we don't need.

        # XXX AndrewBennetts 2006-05-30:
        #    sprout also fails to preserve the repository format!  Bug #47494.
        #    Here's what it should look like:
        #        source = self._source_branch
        #        revision = source.last_revision()
        #        bzrdir = source.bzrdir.sprout(self.dest, revision_id=revision)
        #        return bzrdir.open_branch()
        #    For now, do it the dumb way:
        os.makedirs(self.dest)
        bzrdir_format = self._source_branch.bzrdir._format
        bzrdir = bzrdir_format.initialize(self.dest)
        repo_format = self._source_branch.repository._format
        repo = repo_format.initialize(bzrdir)
        branch_format = self._source_branch._format
        branch = branch_format.initialize(bzrdir)
        branch.pull(self._source_branch)
        return branch
        

    def _mirrorFailed(self, error_msg):
        """Log that the mirroring of this branch failed."""
        self.branch_status_client.mirrorFailed(self.branch_id, str(error_msg))

    def mirror(self):
        """Open source and destination branches and pull source into
        destination.
        """
        self.branch_status_client.startMirroring(self.branch_id)

        try: 
            self._openSourceBranch()
            self._mirrorToDestBranch()
        # add further encountered errors from the production runs here
        # ------ HERE ---------
        #
        except urllib2.HTTPError, e:
            msg = str(e)
            if int(e.code) == httplib.UNAUTHORIZED:
                # Maybe this will be caught in bzrlib one day, and then we'll
                # be able to get rid of this.
                # https://launchpad.net/products/bzr/+bug/42383
                msg = 'Private branch; required authentication'
            self._mirrorFailed(msg)

        except socket.error, e:
            msg = 'A socket error occurred: %s' % str(e)
            self._mirrorFailed(msg)

        except bzrlib.errors.UnsupportedFormatError, e:
            msg = ("The supermirror does not support branches from before "
                   "bzr 0.7. Please upgrade the branch using bzr upgrade.")
            self._mirrorFailed(msg)

        except bzrlib.errors.UnknownFormatError, e:
            if e.args[0].count('\n') >= 2:
                msg = 'Not a branch'
            else:
                msg = 'Unknown branch format: %s' % e.args[0]
            self._mirrorFailed(msg)

        except bzrlib.errors.ParamikoNotPresent, e:
            msg = ("The supermirror does not support mirroring branches "
                   "from SFTP URLs. Please register a HTTP location for "
                   "this branch.")
            self._mirrorFailed(msg)

        except bzrlib.errors.NotBranchError, e:
            self._mirrorFailed(e)

        except bzrlib.errors.BzrError, e:
            self._mirrorFailed(e)

        else:
            last_rev = self._dest_branch.last_revision()
            if last_rev is None:
                last_rev = NULL_REVISION
            self.branch_status_client.mirrorComplete(self.branch_id, last_rev)

    def __eq__(self, other):
        return self.source == other.source and self.dest == other.dest

    def __repr__(self):
        return ("<BranchToMirror source=%s dest=%s at %x>" % 
                (self.source, self.dest, id(self)))

