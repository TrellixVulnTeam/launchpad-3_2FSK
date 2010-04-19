# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Internal Codehosting API interfaces."""

__metaclass__ = type
__all__ = [
    'BRANCH_TRANSPORT',
    'CONTROL_TRANSPORT',
    'ICodehosting',
    'ICodehostingApplication',
    'LAUNCHPAD_ANONYMOUS',
    'LAUNCHPAD_SERVICES',
    'READ_ONLY',
    'WRITABLE',
    ]

from zope.interface import Interface

from canonical.launchpad.webapp.interfaces import ILaunchpadApplication
from canonical.launchpad.validators.name import valid_name

# When LAUNCHPAD_SERVICES is provided as a login ID to XML-RPC methods, they
# bypass the normal security checks and give read-only access to all branches.
# This allows Launchpad services like the puller and branch scanner to access
# private branches.
LAUNCHPAD_SERVICES = '+launchpad-services'
assert not valid_name(LAUNCHPAD_SERVICES), (
    "%r should *not* be a valid name." % (LAUNCHPAD_SERVICES,))

# When LAUNCHPAD_ANONYMOUS is passed, the XML-RPC methods behave as if no user
# was logged in.
LAUNCHPAD_ANONYMOUS = '+launchpad-anonymous'
assert not valid_name(LAUNCHPAD_ANONYMOUS), (
    "%r should *not* be a valid name." % (LAUNCHPAD_ANONYMOUS,))

# These are used as permissions for getBranchInformation.
READ_ONLY = 'r'
WRITABLE = 'w'

# Indicates that a path's real location is on a branch transport.
BRANCH_TRANSPORT = 'BRANCH_TRANSPORT'
# Indicates that a path points to a control directory.
CONTROL_TRANSPORT = 'CONTROL_TRANSPORT'


class ICodehostingApplication(ILaunchpadApplication):
    """Branch Puller application root."""


class ICodehosting(Interface):
    """The codehosting XML-RPC interface to Launchpad.

    Published at 'codehosting' on the private XML-RPC server.

    The code hosting service and puller use this to register branches, to
    retrieve information about a user's branches, and to update their status.
    """

    def acquireBranchToPull(branch_type_names):
        """Return a Branch to pull and mark it as mirror-started.

        :param branch_type_names: Only consider branches of these type names.
            An empty list means consider HOSTED, MIRRORED and IMPORTED
            branches.
        :return: A 5-tuple::

              (branch_id, pull_url, unique_name, default_branch, branch_type)

            where:

              * branch_id is the database id of the branch,
              * pull_url is where to pull from,
              * unique_name is the unique_name of the branch,
              * default_branch is the unique name of the default stacked on
                branch for the branch's target (or '' if there is no such
                branch), and
              * branch_type is one of 'hosted', 'mirrored', or 'imported'.

            or (), the empty tuple, if there is no branch to pull.
        """

    def startMirroring(branchID):
        """Notify Launchpad that the given branch has started mirroring.

        The last_mirror_attempt field of the given branch record will be
        updated appropriately.

        :param branchID: The database ID of the given branch.
        :returns: True if the branch status was successfully updated.
            `NoBranchWithID` fault if there's no branch with the given id.
        """

    def mirrorComplete(branchID, lastRevisionID):
        """Notify Launchpad that the branch has been successfully mirrored.

        In the Launchpad database, the last_mirrored field will be updated to
        match the last_mirror_attempt value, the mirror_failures counter will
        be reset to zero and the next_mirror_time will be set to NULL.

        :param branchID: The database ID of the given branch.
        :param lastRevisionID: The last revision ID mirrored.
        :returns: True if the branch status was successfully updated.
            `NoBranchWithID` fault if there's no branch with the given id.
        """

    def mirrorFailed(branchID, reason):
        """Notify Launchpad that the branch could not be mirrored.

        The mirror_failures counter for the given branch record will be
        incremented and the next_mirror_time will be set to NULL.

        :param branchID: The database ID of the given branch.
        :param reason: A string giving the reason for the failure.
        :returns: True if the branch status was successfully updated.
            `NoBranchWithID` fault if there's no branch with the given id.
        """

    def recordSuccess(name, hostname, date_started, date_completed):
        """Notify Launchpad that a mirror script has successfully completed.

        Create an entry in the ScriptActivity table with the provided data.

        :param name: Name of the script.
        :param hostname: Where the script was running.

        :param date_started: When the script started, as an UTC time tuple.
        :param date_completed: When the script completed (now), as an UTC time
            tuple.
        :returns: True if the ScriptActivity record was successfully inserted.
        """

    def setStackedOn(branch_id, stacked_on_location):
        """Mark a branch as being stacked on another branch.

        :param branch_id: The database ID of the stacked branch.
        :param stacked_on_location: The location of the stacked-on branch.
            For hosted branches, this is normally '/~foo/bar/baz' where
            '~foo/bar/baz' is the unique name of another branch.
        :return: True if the stacked branch information was set successfully.
            `NoBranchWithID` fault if there's no branch with the given id.
            `NoSuchBranch` fault if there's no branch matching
            'stacked_on_location'.
        """

    def createBranch(login_id, branch_path):
        """Register a new hosted branch in Launchpad.

        This is called by the bazaar.launchpad.net server when a user
        pushes a new branch to it.  See also
        https://launchpad.canonical.com/SupermirrorFilesystemHierarchy.

        :param login_id: the person ID of the user creating the branch.
        :param branch_path: the path of the branch to be created. This should
            be a URL-escaped string representing an absolute path.
        :returns: the ID for the new branch or a Fault if the branch cannot be
            created.
        """

    def requestMirror(loginID, branchID):
        """Mark a branch as needing to be mirrored.

        :param loginID: the person ID of the user requesting the mirror.
        :param branchID: a branch ID.
        """

    def branchChanged(branch_id, stacked_on_url, last_revision_id):
        """Record that a branch has been changed.

        This method records the stacked on branch and tip revision id of the
        branch and creates a scan job if the tip revision id has changed.

        :param branchID: The database id of the branch to operate on.
        :param stacked_on_url: The unique name of the branch this branch is
            stacked on, or '' if this branch is not stacked.
        :param last_revision_id: The tip revision ID of the branch.
        """

    def translatePath(requester_id, path):
        """Translate 'path' so that the codehosting transport can access it.

        :param requester_id: the database ID of the person requesting the
            path translation.
        :param path: the path being translated. This should be a URL escaped
            string representing an absolute path.

        :raise `PathTranslationError`: if 'path' cannot be translated.
        :raise `InvalidPath`: if 'path' is known to be invalid.
        :raise `PermissionDenied`: if the requester cannot see the branch.

        :returns: (transport_type, transport_parameters, path_in_transport)
            where 'transport_type' is one of BRANCH_TRANSPORT or
            CONTROL_TRANSPORT, 'transport_parameters' is a dict of data that
            the client can use to construct the transport and
            'path_in_transport' is a path relative to that transport. e.g.
            (BRANCH_TRANSPORT, {'id': 3, 'writable': False}, '.bzr/README').
        """
