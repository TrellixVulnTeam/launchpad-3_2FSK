# Copyright 2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0213

"""Internal Codehosting API interfaces."""

__metaclass__ = type
__all__ = [
    'BRANCH_TRANSPORT',
    'CONTROL_TRANSPORT',
    'IBranchPuller',
    'IBranchPullerApplication',
    'IBranchFileSystem',
    'IBranchFileSystemApplication',
    'LAUNCHPAD_SERVICES',
    'NOT_FOUND_FAULT_CODE',
    'PERMISSION_DENIED_FAULT_CODE',
    'READ_ONLY',
    'WRITABLE',
    ]

from zope.interface import Interface

from canonical.launchpad.webapp.interfaces import ILaunchpadApplication
from canonical.launchpad.validators.name import valid_name

# When this is provided as a login ID to getBranchInformation, the method
# bypasses the normal security checks and returns the branch ID and the
# READ_ONLY permission bit. This allows Launchpad services like the puller and
# branch scanner to access private branches.
LAUNCHPAD_SERVICES = '+launchpad-services'
assert not valid_name(LAUNCHPAD_SERVICES), (
    "%r should *not* be a valid name." % (LAUNCHPAD_SERVICES,))

# These are used as permissions for getBranchInformation.
READ_ONLY = 'r'
WRITABLE = 'w'

# Indicates that a path's real location is on a branch transport.
BRANCH_TRANSPORT = 'BRANCH_TRANSPORT'
# Indicates that a path points to a control directory.
CONTROL_TRANSPORT = 'CONTROL_TRANSPORT'


class IBranchPullerApplication(ILaunchpadApplication):
    """Branch Puller application root."""


class IBranchPuller(Interface):
    """The puller's interface to the rest of Launchpad.

    Published at 'branch_puller' on the private XML-RPC server.
    """

    def getBranchPullQueue(branch_type):
        """Get the list of branches to be pulled by the supermirror.

        :param branch_type: One of 'HOSTED', 'MIRRORED', or 'IMPORTED'.

        :raise UnknownBranchTypeError: if the branch type is unrecognized.

        :returns: a list of (branch_id, pull_url, unique_name) triples, where
        unique_name is ~owner_name/product_name/branch_name, and product_name
        is '+junk' if there is no product associated with the branch.
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


class IBranchFileSystemApplication(ILaunchpadApplication):
    """Branch File System end point root."""


# Values for the faultCode of Faults returned by methods of IBranchFileSystem.
#
# We borrow the numbers from HTTP for familiarity, there's nothing deep in it.
#
# Currently, Faults are only returned by createBranch().  If more methods get
# converted to return Faults, they should use these values if appropriate or
# define more codes here if not.

PERMISSION_DENIED_FAULT_CODE = 403
NOT_FOUND_FAULT_CODE = 404


class IBranchFileSystem(Interface):
    """An interface for dealing with hosted branches in Launchpad.

    Published at `branchfilesystem`.

    The code hosting service uses this to register branches, to retrieve
    information about a user's branches, and to update their status.
    """

    def getBranchInformation(loginID, personName, productName, branchName):
        """Return the database ID and permissions for a branch.

        :param loginID: The login ID for the person asking for the branch
            information. This is used for branch privacy checks.
        :param personName: The owner of the branch.
        :param productName: The product that the branch belongs to. '+junk' is
            allowed.
        :param branchName: The name of the branch.

        :returns: (branch_id, permissions), where 'permissions' is 'w' if the
            user represented by 'loginID' can write to the branch, and 'r' if
            they cannot. If the branch doesn't exist or is not visible to the
            person asking, return ('', '').
        """
        # XXX: JonathanLange 2008-08-05 spec=package-branches: This
        # method will need to change to support source package
        # branches.

    def getDefaultStackedOnBranch(login_id, product_name):
        """Return the URL for the default stacked-on branch of a product.

        :param login_id: The login ID for the person asking for the branch
            information. This is used for branch privacy checks.
        :param product_name: The name of a `Product`.
        :return: An absolute path to a branch on Launchpad. If there is no
            default stacked-on branch configured, return the empty string.
        """
        # XXX: JonathanLange 2008-08-05 spec=package-branches: This
        # method will need to change to support source package
        # branches.

    def createBranch(loginID, personName, productName, branchName):
        """Register a new hosted branch in Launchpad.

        This is called by the bazaar.launchpad.net server when a user
        pushes a new branch to it.  See also
        https://launchpad.canonical.com/SupermirrorFilesystemHierarchy.

        :param loginID: the person ID of the user creating the branch.
        :param personName: the unique name of the owner of the branch.
        :param productName: the unique name of the product that the branch
            belongs to.
        :param branchName: the name for this branch, to be used in URLs.
        :returns: the ID for the new branch or a Fault if the branch cannot be
            created. The faultCode will be PERMISSION_DENIED_FAULT_CODE or
            NOT_FOUND_FAULT_CODE and the faultString will be a description
            suitable to display to the user.
        """
        # XXX: MichaelHudson 2008-08-05 spec=package-branches: This
        # method will need to change to support source package
        # branches.

    def requestMirror(loginID, branchID):
        """Mark a branch as needing to be mirrored.

        :param loginID: the person ID of the user requesting the mirror.
        :param branchID: a branch ID.
        """

    def translatePath(requester_id, path):
        """Translate 'path' so that the codehosting transport can access it.

        :param requester_id: the database ID of the person requesting the
            path translation.
        :param path: the path being translated. This should be a URL escaped
            string.

        :returns: `PathTranslationError` if 'path' cannot be translated.
            (transport_type, transport_parameters, path_in_transport)
        """
