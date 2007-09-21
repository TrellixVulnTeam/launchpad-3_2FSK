# Copyright 2006 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import httplib
import os
import shutil
import socket
import sys
import urllib2

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import (
    BzrError, NotBranchError, ParamikoNotPresent,
    UnknownFormatError, UnsupportedFormatError)
from bzrlib.revision import NULL_REVISION

from canonical.config import config
from canonical.launchpad.interfaces import BranchType
from canonical.launchpad.webapp import errorlog
from canonical.launchpad.webapp.uri import URI


__all__ = [
    'BadUrlSsh',
    'BadUrlLaunchpad',
    'BranchReferenceLoopError',
    'BranchReferenceForbidden',
    'BranchReferenceValueError',
    'BranchToMirror',
    ]


class BadUrlSsh(Exception):
    """Tried to mirror a branch from sftp or bzr+ssh."""


class BadUrlLaunchpad(Exception):
    """Tried to mirror a branch from launchpad.net."""

class BranchReferenceForbidden(Exception):
    """Trying to mirror a branch reference and the branch type does not allow
    references.
    """


class BranchReferenceValueError(Exception):
    """Encountered a branch reference with an unsafe value.

    An unsafe value is a local URL, such as a file:// URL or an http:// URL in
    canonical.com, that may cause disclosure of restricted data.
    """

    def __init__(self, url):
        Exception.__init__(self, url)
        self.url = url


class BranchReferenceLoopError(Exception):
    """Encountered a branch reference cycle.

    A branch reference may point to another branch reference, and so on. A
    branch reference cycle is an infinite loop of references.
    """


def identical_formats(branch_one, branch_two):
    """Check if two branches have the same bzrdir, repo, and branch formats."""
    # XXX AndrewBennetts 2006-05-18 bug=45277:
    # comparing format objects is ugly.
    b1, b2 = branch_one, branch_two
    return (
        b1.bzrdir._format.__class__ == b2.bzrdir._format.__class__ and
        b1.repository._format.__class__ == b2.repository._format.__class__ and
        b1._format.__class__ == b2._format.__class__
    )


class BranchToMirror:
    """This class represents a single branch that needs mirroring.

    It has a source URL, a destination URL, a database id, a unique name and a
    status client which is used to report on the mirror progress.
    """

    def __init__(self, src, dest, branch_status_client, branch_id,
                 unique_name, branch_type):
        self.source = src
        self.dest = dest
        self.branch_status_client = branch_status_client
        self.branch_id = branch_id
        self.unique_name = unique_name
        # The branch_type argument should always be set to a BranchType enum in
        # production use, but it is expected that tests that do not depend on
        # its value will pass None.
        self.branch_type = branch_type
        self._source_branch = None
        self._dest_branch = None

    def _checkSourceUrl(self):
        """Check the validity of the source URL.

        If the source is an absolute path, that means it represents a hosted
        branch, and it does not make sense to check its scheme or hostname. So
        let it pass.

        If the source URL is uses a ssh-based scheme, raise BadUrlSsh. If it is
        in the launchpad.net domain, raise BadUrlLaunchpad.
        """
        if self.source.startswith('/'):
            return
        uri = URI(self.source)
        launchpad_domain = config.launchpad.vhosts.mainsite.hostname
        if uri.underDomain(launchpad_domain):
            raise BadUrlLaunchpad(self.source)
        if uri.scheme in ['sftp', 'bzr+ssh']:
            raise BadUrlSsh(self.source)

    def _checkBranchReference(self):
        """Check whether the source is an acceptable branch reference.

        For HOSTED or IMPORTED branches, branch references are not allowed. For
        MIRRORED branches, branch references are allowed if they do not
        constitute a reference cycle and if they do not point to an unsafe
        location.

        :raise BranchReferenceForbidden: the source location contains a branch
            reference, and branch references are not allowed for this branch
            type.

        :raise BranchReferenceLoopError: the source location contains a branch
            reference that leads to a reference cycle.

        :raise BranchReferenceValueError: the source location contains a branch
            reference that ultimately points to an unsafe location.
        """
        traversed_references = []
        source_location = self.source
        while True:
            reference_value = self._getBranchReference(source_location)
            if reference_value is None:
                break
            if not self._canTraverseReferences():
                raise BranchReferenceForbidden(reference_value)
            traversed_references.append(source_location)
            if reference_value in traversed_references:
                raise BranchReferenceLoopError()
            reference_value_uri = URI(reference_value)
            if reference_value_uri.scheme == 'file':
                raise BranchReferenceValueError(reference_value)
            source_location = reference_value

    def _canTraverseReferences(self):
        """Whether we can traverse references when mirroring this branch type.

        We do not traverse references for HOSTED branches because that may
        cause us to connect to remote locations, which we do not allow because
        we want hosted branches to be mirrored quickly.

        We do not traverse references for IMPORTED branches because the
        code-import system should never produce branch references.

        We traverse branche references for MIRRORED branches because they
        provide a useful redirection mechanism and we want to be consistent
        with the bzr command line.
        """
        traverse_references_from_branch_type = {
            BranchType.HOSTED: False,
            BranchType.MIRRORED: True,
            BranchType.IMPORTED: False,
            }
        assert self.branch_type in traverse_references_from_branch_type, (
            'Unexpected branch type: %r' % (self.branch_type,))
        return traverse_references_from_branch_type[self.branch_type]

    def _getBranchReference(self, url):
        """Get the branch-reference value at the specified url.

        This method is useful to override in unit tests.
        """
        bzrdir = BzrDir.open(url)
        return bzrdir.get_branch_reference()

    def _openSourceBranch(self):
        """Open the branch to pull from, useful to override in tests."""
        self._source_branch = Branch.open(self.source)

    def _mirrorToDestBranch(self):
        """Open the branch to pull to, creating a new one if necessary.

        Useful to override in tests.
        """
        try:
            branch = BzrDir.open(self.dest).open_branch()
        except NotBranchError:
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

        # XXX AndrewBennetts 2006-05-30 Bug=47494:
        #    sprout also fails to preserve the repository format!
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

    def _mirrorFailed(self, logger, error_msg):
        """Record that the mirroring of this branch failed.

        Update the branch status in the database and emit a log message.
        """
        self.branch_status_client.mirrorFailed(self.branch_id, str(error_msg))
        logger.info('Recorded failure: %s', str(error_msg))

    def _mirrorSuccessful(self, logger):
        """Record that the mirroring of this branch was successful.

        Update the branch status in the database and emit a log message.
        """
        last_rev = self._dest_branch.last_revision()
        if last_rev is None:
            last_rev = NULL_REVISION
        self.branch_status_client.mirrorComplete(self.branch_id, last_rev)
        logger.info('Successfully mirrored to rev %s', last_rev)

    def _record_oops(self, logger, message=None):
        """Record an oops for the current exception.

        This must only be called while handling an exception.

        :param message: custom explanatory error message. Do not use
            str(exception) to fill in this parameter, it should only be set
            when a human readable error has been explicitely generated.
        """
        request = errorlog.ScriptRequest([
            ('branch_id', self.branch_id),
            ('source', self.source),
            ('dest', self.dest),
            ('error-explanation', message)])
        request.URL = self._canonical_url()
        errorlog.globalErrorUtility.raising(sys.exc_info(), request)
        logger.info('Recorded %s', request.oopsid)

    def _canonical_url(self):
        """Custom implementation of canonical_url(branch) for error reporting.

        The actual canonical_url method cannot be used because we do not have
        access to real content objects.
        """
        if config.launchpad.vhosts.use_https:
            scheme = 'https'
        else:
            scheme = 'http'
        hostname = config.launchpad.vhosts.code.hostname
        return scheme + '://' + hostname + '/~' + self.unique_name

    def mirror(self, logger):
        """Open source and destination branches and pull source into
        destination.
        """
        self.branch_status_client.startMirroring(self.branch_id)
        logger.info('Mirroring branch %d: %s to %s',
                    self.branch_id, self.source, self.dest)

        try:
            self._checkSourceUrl()
            self._checkBranchReference()
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
                msg = "Authentication required."
            self._record_oops(logger, msg)
            self._mirrorFailed(logger, msg)

        except socket.error, e:
            msg = 'A socket error occurred: %s' % str(e)
            self._record_oops(logger, msg)
            self._mirrorFailed(logger, msg)

        except UnsupportedFormatError, e:
            msg = ("Launchpad does not support branches from before "
                   "bzr 0.7. Please upgrade the branch using bzr upgrade.")
            self._record_oops(logger, msg)
            self._mirrorFailed(logger, msg)

        except UnknownFormatError, e:
            self._record_oops(logger)
            self._mirrorFailed(logger, e)

        except (ParamikoNotPresent, BadUrlSsh), e:
            msg = ("Launchpad cannot mirror branches from SFTP and SSH URLs."
                   " Please register a HTTP location for this branch.")
            self._record_oops(logger, msg)
            self._mirrorFailed(logger, msg)

        except BadUrlLaunchpad:
            msg = "Launchpad does not mirror branches from Launchpad."
            self._record_oops(logger, msg)
            self._mirrorFailed(logger, msg)

        except NotBranchError, e:
            hosted_branch_error = NotBranchError(
                "sftp://bazaar.launchpad.net/~%s" % self.unique_name)
            message_by_type = {
                BranchType.HOSTED: str(hosted_branch_error),
                BranchType.IMPORTED: "Not a branch.",
                }
            msg = message_by_type.get(self.branch_type, str(e))
            self._record_oops(logger, msg)
            self._mirrorFailed(logger, msg)

        except BranchReferenceForbidden, e:
            msg = ("Branch references are not allowed for branches of type %s."
                   % (self.branch_type.title,))
            self._record_oops(logger, msg)
            self._mirrorFailed(logger, msg)

        except BranchReferenceValueError, e:
            msg = "Bad branch reference value: %s" % (e.url,)
            self._record_oops(logger, msg)
            self._mirrorFailed(logger, msg)

        except BranchReferenceLoopError, e:
            msg = "Circular branch reference."
            self._record_oops(logger, msg)
            self._mirrorFailed(logger, msg)

        except BzrError, e:
            self._record_oops(logger)
            self._mirrorFailed(logger, e)

        except (KeyboardInterrupt, SystemExit):
            # Do not record OOPS for those exceptions.
            raise

        except:
            # Any exception not handled specially is recorded as OOPS.
            self._record_oops(logger)
            raise

        else:
            self._mirrorSuccessful(logger)

    def __eq__(self, other):
        return self.source == other.source and self.dest == other.dest

    def __repr__(self):
        return ("<BranchToMirror source=%s dest=%s at %x>" %
                (self.source, self.dest, id(self)))
