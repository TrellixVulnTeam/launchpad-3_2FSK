# Copyright 2006-2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import httplib
import socket
import sys
import urllib2

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib import errors
from bzrlib.plugins.loom.branch import LoomSupport
from bzrlib.progress import DummyProgress
from bzrlib.remote import RemoteBranch, RemoteBzrDir, RemoteRepository
from bzrlib.transport import get_transport
from bzrlib import urlutils
import bzrlib.ui

from canonical.config import config
from canonical.codehosting import ProgressUIFactory
from canonical.codehosting.branchfs import get_puller_server
from canonical.codehosting.bzrutils import get_branch_stacked_on_url
from canonical.codehosting.puller import get_lock_id_for_branch_id
from canonical.launchpad.interfaces.branch import (
    BranchType, get_blacklisted_hostnames)
from canonical.launchpad.webapp import errorlog
from canonical.launchpad.webapp.uri import URI, InvalidURIError


__all__ = [
    'BadUrl',
    'BadUrlFile',
    'BadUrlLaunchpad',
    'BadUrlSsh',
    'BranchMirrorer',
    'BranchPolicy',
    'BranchLoopError',
    'BranchReferenceForbidden',
    'BranchReferenceValueError',
    'get_canonical_url_for_branch_name',
    'install_worker_ui_factory',
    'PullerWorker',
    'PullerWorkerProtocol',
    'StackedOnBranchNotFound',
    'URLChecker',
    ]


class BadUrl(Exception):
    """Tried to mirror a branch from a bad URL."""


class BadUrlSsh(BadUrl):
    """Tried to mirror a branch from sftp or bzr+ssh."""


class BadUrlLaunchpad(BadUrl):
    """Tried to mirror a branch from launchpad.net."""


class BadUrlScheme(BadUrl):
    """Found a URL with an untrusted scheme."""
    def __init__(self, scheme, url):
        BadUrl.__init__(self, scheme, url)
        self.scheme = scheme


class BranchReferenceForbidden(Exception):
    """Trying to mirror a branch reference and the branch type does not allow
    references.
    """


class BranchLoopError(Exception):
    """Encountered a branch reference cycle.

    A branch reference may point to another branch reference, and so on. A
    branch reference cycle is an infinite loop of references.
    XXX
    """


class StackedOnBranchNotFound(Exception):
    """Couldn't find the stacked-on branch."""


def get_stacked_on_url(branch):
    """Get the stacked-on URL for 'branch', return None if it not stacked."""
    try:
        return branch.get_stacked_on_url()
    except (errors.NotStacked, errors.UnstackableBranchFormat):
        return None


def get_canonical_url_for_branch_name(unique_name):
    """Custom implementation of canonical_url(branch) for error reporting.

    The actual `canonical_url` function cannot be used because we do not have
    access to real content objects.
    """
    if config.vhosts.use_https:
        scheme = 'https'
    else:
        scheme = 'http'
    hostname = config.vhost.code.hostname
    return scheme + '://' + hostname + '/' + unique_name


class PullerWorkerProtocol:
    """The protocol used to communicate with the puller scheduler.

    This protocol notifies the scheduler of events such as startMirroring,
    mirrorSucceeded and mirrorFailed.
    """

    def __init__(self, output):
        self.out_stream = output

    def sendNetstring(self, string):
        self.out_stream.write('%d:%s,' % (len(string), string))

    def sendEvent(self, command, *args):
        self.sendNetstring(command)
        self.sendNetstring(str(len(args)))
        for argument in args:
            self.sendNetstring(str(argument))

    def setStackedOn(self, stacked_on_location):
        self.sendEvent('setStackedOn', stacked_on_location)

    def startMirroring(self):
        self.sendEvent('startMirroring')

    def mirrorDeferred(self):
        # Called when we want to try mirroring again later without indicating
        # success or failure.
        self.sendEvent('mirrorDeferred')

    def mirrorSucceeded(self, last_revision):
        self.sendEvent('mirrorSucceeded', last_revision)

    def mirrorFailed(self, message, oops_id):
        self.sendEvent('mirrorFailed', message, oops_id)

    def progressMade(self):
        self.sendEvent('progressMade')

    def log(self, fmt, *args):
        self.sendEvent('log', fmt % args)


def get_vfs_format_classes(branch):
    """Return the vfs classes of the branch, repo and bzrdir formats.

    'vfs' here means that it will return the underlying format classes of a
    remote branch.
    """
    if isinstance(branch, RemoteBranch):
        branch._ensure_real()
        branch = branch._real_branch
    repository = branch.repository
    if isinstance(repository, RemoteRepository):
        repository._ensure_real()
        repository = repository._real_repository
    bzrdir = branch.bzrdir
    if isinstance(bzrdir, RemoteBzrDir):
        bzrdir._ensure_real()
        bzrdir = bzrdir._real_bzrdir
    return (
        branch._format.__class__,
        repository._format.__class__,
        bzrdir._format.__class__,
        )


def identical_formats(branch_one, branch_two):
    """Check if two branches have the same bzrdir, repo, and branch formats.
    """
    return (get_vfs_format_classes(branch_one) ==
            get_vfs_format_classes(branch_two))


class BranchPolicy:
    """Policy on how to mirror branches.

    In particular, a policy determines which branches are safe to mirror by
    checking their URLs and deciding whether or not to follow branch
    references. A policy also determines how the mirrors of branches should be
    stacked.
    """

    def getStackedOnURLForDestinationBranch(self, source_branch,
                                            destination_url):
        """Return the URL of the branch to stack the mirrored copy on.

        By default, we stacked the copy on the same URL as the source,
        relative to the new URL.

        :param source_branch: The branch to be mirrored.
        :param destination_url: The place to mirror it to.
        :return: The URL of the branch to stack the mirrored copy on. None if
            the mirrored copy should not be stacked.
        """
        return get_stacked_on_url(source_branch)

    def shouldFollowReferences(self):
        """Whether we traverse references when mirroring.

        Subclasses must override this method.

        If we encounter a branch reference and this returns false, an error is
        raised.

        :returns: A boolean to indicate whether to follow a branch reference.
        """
        raise NotImplementedError(self.shouldFollowReferences)

    def transformFallbackLocation(self, branch, url):
        """XXX."""
        raise NotImplementedError(self.transformFallbackLocation)

    def checkOneURL(self, url):
        """Check the safety of the source URL.

        Subclasses must override this method.

        :param url: The source URL to check.
        :raise BadUrl: subclasses are expected to raise this or a subclass
            when it finds a URL it deems to be unsafe.
        """
        raise NotImplementedError(self.checkOneURL)


class BranchMirrorer(object):
    """A `BranchMirrorer` safely makes mirrors of branches.

    A `BranchMirrorer` has a `BranchPolicy` to tell it which URLs are safe to
    accesss, whether or not to follow branch references and how to stack
    branches when they are mirrored.

    The mirrorer knows how to follow branch references, create new mirrors,
    update existing mirrors, determine stacked-on branches and the like.

    Public methods are `open` and `mirror`.
    """

    def __init__(self, policy, log=None):
        """Construct a branch opener with 'policy'.

        :param policy: A `BranchPolicy` that tells us what URLs are valid and
            similar things.
        :param log: A callable which can be called with a format string and
            arguments to log messages in the scheduler, or None, in which case
            log messages are discarded.
        """
        Branch.hooks.install_named_hook(
            'transform_fallback_location', self._transformFallbackLocation,
            'BranchMirrorer._transformFallbackLocation')
        self.policy = policy
        if log is not None:
            self.log = log
        else:
            self.log = lambda *args: None

    def open(self, url):
        """Open the Bazaar branch at url, first checking for safety.

        What safety means is defined by a subclasses `followReference` and
        `checkOneURL` methods.
        """
        self._seen_urls = set()
        url = self.checkAndFollowBranchReference(url)
        return Branch.open(url)

    def _transformFallbackLocation(self, branch, url):
        """XXX."""
        new_url = self.policy.transformFallbackLocation(branch, url)
        return self.checkAndFollowBranchReference(new_url)

    def followReference(self, url):
        """Get the branch-reference value at the specified url.

        This exists as a separate method only to be overriden in unit tests.
        """
        bzrdir = BzrDir.open(url)
        return bzrdir.get_branch_reference()

    def checkAndFollowBranchReference(self, url):
        """
        :raise BranchLoopError: If the branch references form a loop.
        :raise BranchReferenceForbidden: If this opener forbids branch
            references.
        """
        while True:
            if url in self._seen_urls:
                raise BranchLoopError()
            self.policy.checkOneURL(url)
            self._seen_urls.add(url)
            next_url = self.followReference(url)
            if next_url is None:
                return url
            url = next_url
            if not self.policy.shouldFollowReferences():
                raise BranchReferenceForbidden(url)

    def createDestinationBranch(self, source_branch, destination_url):
        """Create a destination branch for 'source_branch'.

        Creates a branch at 'destination_url' that is a mirror of
        'source_branch'. Any content already at 'destination_url' will be
        deleted.

        If 'source_branch' is stacked, then the destination branch will be
        stacked on the same URL, relative to 'destination_url'.

        :param source_branch: The Bazaar branch that will be mirrored.
        :param destination_url: The place to make the destination branch. This
            URL must point to a writable location.
        :return: The destination branch.
        """
        dest_transport = get_transport(destination_url)
        if dest_transport.has('.'):
            dest_transport.delete_tree('.')
        bzrdir = source_branch.bzrdir
        stacked_on_url = (
            self.policy.getStackedOnURLForDestinationBranch(
                source_branch, destination_url))
        if stacked_on_url is not None:
            # We resolve the stacked_on_url relative to the destination_url
            # because a common case for stacked_on_url will be
            # /~user/project/branch and we want to check the branch already
            # exists in the mirrored area.
            stacked_on_url = urlutils.join(destination_url, stacked_on_url)
            try:
                Branch.open(stacked_on_url)
            except errors.NotBranchError:
                raise StackedOnBranchNotFound()
        if isinstance(source_branch, LoomSupport):
            # Looms suck.
            revision_id = None
        else:
            revision_id = 'null:'
        bzrdir.clone_on_transport(dest_transport, revision_id=revision_id)
        branch = Branch.open(destination_url)
        return branch

    def openDestinationBranch(self, source_branch, destination_url):
        """Open or create the destination branch at 'destination_url'.

        :param source_branch: The Bazaar branch that will be mirrored.
        :param destination_url: The place to make the destination branch. This
            URL must point to a writable location.
        :return: (branch, up_to_date), where 'branch' is the destination
            branch, and 'up_to_date' is a boolean saying whether the returned
            branch is up-to-date with the source branch.
        """
        try:
            branch = Branch.open(destination_url)
        except errors.NotBranchError:
            # Make a new branch in the same format as the source branch.
            return self.createDestinationBranch(
                source_branch, destination_url)
        # Check that destination branch is in the same format as the source.
        if identical_formats(source_branch, branch):
            return branch
        self.log('Formats differ.')
        return self.createDestinationBranch(source_branch, destination_url)

    def updateBranch(self, source_branch, dest_branch):
        """Bring 'dest_branch' up-to-date with 'source_branch'.

        This methdo pulls 'source_branch' into 'dest_branch' and sets the
        stacked-on URL of 'dest_branch' to match 'source_branch'.

        This method assumes that 'source_branch' and 'dest_branch' both have
        the same format.
        """
        # Make sure the mirrored branch is stacked the same way as the
        # source branch.
        stacked_on_url = self.policy.getStackedOnURLForDestinationBranch(
            source_branch, dest_branch.base)
        try:
            dest_branch.set_stacked_on_url(stacked_on_url)
        except (errors.UnstackableRepositoryFormat,
                errors.UnstackableBranchFormat):
            pass
        except errors.NotBranchError:
            raise StackedOnBranchNotFound()
        dest_branch.pull(source_branch, overwrite=True)

    def mirror(self, source_branch, destination_url):
        """Mirror 'source_branch' to 'destination_url'."""
        branch = self.openDestinationBranch(source_branch, destination_url)
        # If the branch is locked, try to break it. Our special UI factory
        # will allow the breaking of locks that look like they were left
        # over from previous puller worker runs. We will block on other
        # locks and fail if they are not broken before the timeout expires
        # (currently 5 minutes).
        if branch.get_physical_lock_status():
            branch.break_lock()
        self.updateBranch(source_branch, branch)
        return branch


class HostedBranchPolicy(BranchPolicy):
    """Mirroring policy for HOSTED branches.

    In summary:

     - don't follow references,
     - assert we're pulling from a lp-hosted:/// URL.
    """

    def shouldFollowReferences(self):
        """See `BranchPolicy.shouldFollowReferences`.

        We do not traverse references for HOSTED branches because that may
        cause us to connect to remote locations, which we do not allow because
        we want hosted branches to be mirrored quickly.
        """
        return False

    def checkOneURL(self, url):
        """See `BranchPolicy.checkOneURL`.

        If the URL we are mirroring from is anything but a
        lp-hosted:///~user/project/branch URL, something has gone badly wrong,
        so we raise AssertionError if that's happened.
        """
        uri = URI(url)
        if uri.scheme != 'lp-hosted':
            raise AssertionError(
                "Non-hosted url %r for hosted branch." % url)


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
        their product.
        """
        return self.stacked_on_url

    def shouldFollowReferences(self):
        """See `BranchPolicy.shouldFollowReferences`.

        We traverse branch references for MIRRORED branches because they
        provide a useful redirection mechanism and we want to be consistent
        with the bzr command line.
        """
        return True

    def checkOneURL(self, url):
        """See `BranchPolicy.checkOneURL`.

        We refuse to mirror from Launchpad or a ssh-like or file URL.
        """
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

    def shouldFollowReferences(self):
        """See `BranchPolicy.shouldFollowReferences`.

        We do not traverse references for IMPORTED branches because the
        code-import system should never produce branch references.
        """
        return False

    def checkOneURL(self, url):
        """See `BranchPolicy.checkOneURL`.

        If the URL we are mirroring from does not start how we expect the pull
        URLs of import branches to start, something has gone badly wrong, so
        we raise AssertionError if that's happened.
        """
        if not url.startswith(config.launchpad.bzr_imports_root_url):
            raise AssertionError(
                "Bogus URL for imported branch: %r" % url)


class PullerWorker:
    """This class represents a single branch that needs mirroring.

    It has a source URL, a destination URL, a database id, a unique name and a
    status client which is used to report on the mirror progress.
    """

    def _checkerForBranchType(self, branch_type):
        """Return a `BranchMirrorer` with an appropriate `BranchPolicy`.

        :param branch_type: A `BranchType`. The policy of the mirrorer will
            be based on this.
        :return: A `BranchMirrorer`.
        """
        if branch_type == BranchType.HOSTED:
            policy = HostedBranchPolicy()
        elif branch_type == BranchType.MIRRORED:
            policy = MirroredBranchPolicy(self.default_stacked_on_url)
        elif branch_type == BranchType.IMPORTED:
            policy = ImportedBranchPolicy()
        else:
            raise AssertionError(
                "Unexpected branch type: %r" % branch_type)
        if self.protocol is not None:
            log = self.protocol.log
        else:
            log = None
        return BranchMirrorer(policy, log)

    def __init__(self, src, dest, branch_id, unique_name, branch_type,
                 default_stacked_on_url, protocol, branch_mirrorer=None,
                 oops_prefix=None):
        """Construct a `PullerWorker`.

        :param src: The URL to pull from.
        :param dest: The URL to pull into.
        :param branch_id: The database ID of the branch we're pulling.
        :param unique_name: The unique_name of the branch we're pulling
            (without the tilde).
        :param branch_type: A member of the BranchType enum.  It is expected
            that tests that do not depend on its value will pass None.
        :param default_stacked_on_url: The unique name of the default
            stacked-on branch for the product of the branch we are mirroring.
            None or '' if there is no such branch.
        :param protocol: An instance of `PullerWorkerProtocol`.
        :param branch_mirrorer: An instance of `BranchMirrorer`.  If not passed,
            one will be chosen based on the value of `branch_type`.
        :param oops_prefix: An oops prefix to pass to `setOopsToken` on the
            global ErrorUtility.
        """
        self.source = src
        self.dest = dest
        self.branch_id = branch_id
        self.unique_name = unique_name
        self.branch_type = branch_type
        if default_stacked_on_url == '':
            default_stacked_on_url = None
        self.default_stacked_on_url = default_stacked_on_url
        self.protocol = protocol
        if protocol is not None:
            self.protocol.branch_id = branch_id
        if branch_mirrorer is None:
            branch_mirrorer = self._checkerForBranchType(branch_type)
        self.branch_mirrorer = branch_mirrorer
        if oops_prefix is not None:
            errorlog.globalErrorUtility.setOopsToken(oops_prefix)

    def _record_oops(self, message=None):
        """Record an oops for the current exception.

        This must only be called while handling an exception.

        :param message: custom explanatory error message. Do not use
            str(exception) to fill in this parameter, it should only be set
            when a human readable error has been explicitly generated.
        """
        request = errorlog.ScriptRequest([
            ('branch_id', self.branch_id), ('source', self.source),
            ('dest', self.dest), ('error-explanation', str(message))])
        request.URL = get_canonical_url_for_branch_name(self.unique_name)
        errorlog.globalErrorUtility.raising(sys.exc_info(), request)
        return request.oopsid

    def _mirrorFailed(self, error):
        oops_id = self._record_oops(error)
        self.protocol.mirrorFailed(error, oops_id)

    def mirrorWithoutChecks(self):
        """Mirror the source branch to the destination branch.

        This method doesn't do any error handling or send any messages via the
        reporting protocol -- a "naked mirror", if you will. This is
        particularly useful for tests that want to mirror a branch and be
        informed immediately of any errors.
        """
        server = get_puller_server()
        server.setUp()
        try:
            source_branch = self.branch_mirrorer.open(self.source)
            stacked_on_url = get_stacked_on_url(source_branch)
            if stacked_on_url is not None:
                self.protocol.setStackedOn(stacked_on_url)
            return self.branch_mirrorer.mirror(source_branch, self.dest)
        finally:
            server.tearDown()

    def mirror(self):
        """Open source and destination branches and pull source into
        destination.
        """
        self.protocol.startMirroring()
        try:
            dest_branch = self.mirrorWithoutChecks()
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
            self._mirrorFailed(msg)

        except socket.error, e:
            msg = 'A socket error occurred: %s' % str(e)
            self._mirrorFailed(msg)

        except errors.UnsupportedFormatError, e:
            msg = ("Launchpad does not support branches from before "
                   "bzr 0.7. Please upgrade the branch using bzr upgrade.")
            self._mirrorFailed(msg)

        except errors.UnknownFormatError, e:
            self._mirrorFailed(e)

        except (errors.ParamikoNotPresent, BadUrlSsh), e:
            msg = ("Launchpad cannot mirror branches from SFTP and SSH URLs."
                   " Please register a HTTP location for this branch.")
            self._mirrorFailed(msg)

        except BadUrlLaunchpad:
            msg = "Launchpad does not mirror branches from Launchpad."
            self._mirrorFailed(msg)

        except BadUrlScheme, e:
            msg = "Launchpad does not mirror %s:// URLs." % e.scheme
            self._mirrorFailed(msg)

        except errors.NotBranchError, e:
            hosted_branch_error = errors.NotBranchError(
                "lp:%s" % self.unique_name)
            message_by_type = {
                BranchType.HOSTED: str(hosted_branch_error),
                BranchType.IMPORTED: "Not a branch.",
                }
            msg = message_by_type.get(self.branch_type, str(e))
            self._mirrorFailed(msg)

        except BranchReferenceForbidden, e:
            msg = ("Branch references are not allowed for branches of type "
                   "%s." % (self.branch_type.title,))
            self._mirrorFailed(msg)

        except BranchReferenceLoopError, e:
            msg = "Circular branch reference."
            self._mirrorFailed(msg)

        except errors.BzrError, e:
            self._mirrorFailed(e)

        except InvalidURIError, e:
            self._mirrorFailed(e)

        except StackedOnBranchNotFound:
            self.protocol.mirrorDeferred()

        except (KeyboardInterrupt, SystemExit):
            # Do not record OOPS for those exceptions.
            raise

        else:
            last_rev = dest_branch.last_revision()
            self.protocol.mirrorSucceeded(last_rev)

    def __eq__(self, other):
        return self.source == other.source and self.dest == other.dest

    def __repr__(self):
        return ("<PullerWorker source=%s dest=%s at %x>" %
                (self.source, self.dest, id(self)))


class WorkerProgressBar(DummyProgress):
    """A progress bar that informs a PullerWorkerProtocol of progress."""

    def _event(self, *args, **kw):
        """Inform the PullerWorkerProtocol of progress.

        This method is attached to the class as all of the progress bar
        methods: tick, update, child_update, clear and note.
        """
        self.puller_worker_protocol.progressMade()

    tick = _event
    update = _event
    child_update = _event
    clear = _event
    note = _event

    def child_progress(self, **kwargs):
        """As we don't care about nesting progress bars, return self."""
        return self


class PullerWorkerUIFactory(ProgressUIFactory):
    """An UIFactory that always says yes to breaking locks."""

    def get_boolean(self, prompt):
        """If we're asked to break a lock like a stale lock of ours, say yes.
        """
        assert prompt.startswith('Break lock'), (
            "Didn't expect prompt %r" % (prompt,))
        branch_id = self.puller_worker_protocol.branch_id
        if get_lock_id_for_branch_id(branch_id) in prompt:
            return True
        else:
            return False


def install_worker_ui_factory(puller_worker_protocol):
    """Install a special UIFactory for puller workers.

    Our factory does two things:

    1) Create progress bars that inform a PullerWorkerProtocol of progress.
    2) Break locks if and only if they appear to be stale locks
       created by another puller worker process.
    """
    def factory(*args, **kw):
        r = WorkerProgressBar(*args, **kw)
        r.puller_worker_protocol = puller_worker_protocol
        return r
    bzrlib.ui.ui_factory = PullerWorkerUIFactory(factory)
    bzrlib.ui.ui_factory.puller_worker_protocol = puller_worker_protocol
