# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface for build farm job behaviors."""

__metaclass__ = type

__all__ = [
    'BuildBehaviorMismatch',
    'IBuildFarmJobBehavior',
    ]

from zope.interface import Interface


class BuildBehaviorMismatch(Exception):
    """
    A general exception that can be raised when the builder's current behavior
    does not match the expected behavior.
    """


class IBuildFarmJobBehavior(Interface):

    def setBuilderInteractor(interactor):
        """Sets the associated `BuilderInteractor` for this instance."""

    def logStartBuild(logger):
        """Log the start of a specific build queue item.

        The form of the log message will vary depending on the type of build.
        :param build_queue_item: A BuildQueueItem to build.
        :param logger: A logger to be used to log diagnostic information.
        """

    def dispatchBuildToSlave(build_queue_item_id, logger):
        """Dispatch a specific build to the slave.

        :param build_queue_item_id: An identifier for the build queue item.
        :param logger: A logger to be used to log diagnostic information.
        """

    def verifyBuildRequest(logger):
        """Carry out any pre-build checks.

        :param logger: A logger to be used to log diagnostic information.
        """

    def generateSlaveBuildCookie(self):
        """Produce a cookie for the slave as a token of the job it's doing.

        The cookie should uniquely represent the current dispatch of the
        current build.
        """

    def updateSlaveStatus(raw_slave_status, status):
        """Update the slave status dict with custom values for this behavior.

        :param raw_slave_status: The value returned by the build slave's
           status() method.
        :param status: A dict of the processed slave status values provided
           by all types: builder_status, build_id, and optionally build_status
           or logtail. This should have any behaviour-specific values
           added to it.
        """

    def handleStatus(status, librarian, slave_status):
        """Update the build from a WAITING slave result.

        :param status: The tail of the BuildStatus (eg. OK or PACKAGEFAIL).
        :param librarian: An `ILibrarianClient` to use for file uploads.
        :param slave_status: Slave status from `BuilderInteractor.slaveStatus`.
        """
