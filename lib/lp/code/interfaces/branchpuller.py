# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""The public interface to the model of the branch puller."""

__metaclass__ = type
__all__ = [
    'IBranchPuller',
    ]


from zope.interface import Attribute, Interface


class IBranchPuller(Interface):
    """The interface to the database for the branch puller."""

    MAXIMUM_MIRROR_FAILURES = Attribute(
        "The maximum number of failures before we disable mirroring.")

    MIRROR_TIME_INCREMENT = Attribute(
        "How frequently we mirror branches.")

    def acquireBranchToPull():
        """Return a Branch to pull and mark it as mirror-started.

        :return: The branch object to pull next, or ``None`` if there is no
            branch to pull.
        """
