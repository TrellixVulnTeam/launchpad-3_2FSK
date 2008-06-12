# Copyright 2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""BugTrackerPerson interface."""

__metaclass__ = type
__all__ = [
    'IBugTrackerPerson',
    'IBugTrackerPersonSet',
    'BugTrackerNameAlreadyTaken',
    ]

from zope.interface import Interface
from zope.schema import Datetime, Object, Text

from canonical.launchpad import _
from canonical.launchpad.interfaces.bugtracker import IBugTracker
from canonical.launchpad.interfaces.launchpad import IHasBug
from canonical.launchpad.interfaces.person import IPerson


class BugTrackerNameAlreadyTaken(Exception):
    """Raised when an `IBugTrackerPerson` already exists with a given name.
    """


class IBugTrackerPerson(IHasBug):
    """A link between a person and a bugtracker."""

    bugtracker = Object(
        schema=IBugTracker, title=u"The bug.", required=True)
    person = Object(
        schema=IPerson, title=_('Person'), required=True)
    name = Text(
        title=_("The name of the person on the bugtracker."),
        required=True)
    date_created = Datetime(
        title=_('Date Created'), required=True, readonly=True)


class IBugTrackerPersonSet(Interface):
    """A set of IBugTrackerPersons."""

    def ensurePersonForBugTracker(
        self, bugtracker, display_name, email, rationale, creation_comment):
        """Return the correct `IPerson` for a given name and bugtracker.

        :param bugtracker: The `IBugTracker` for which we should have a
            given Person.
        :param display_name: The name of the Person on `bugtracker`.
        :param email: The Person's email address if available. If `email`
            is supplied a Person will be created or retrieved using that
            email address and no `IBugTrackerPerson` records will be created.
        :param rationale: The `PersonCreationRationale` used to create a
            new `IPerson` for this `name` and `bugtracker`, if necessary.
        :param creation_comment: The creation comment for the `IPerson`
            if one is created.
        """

    def getByNameAndBugTracker(name, bugtracker):
        """Return the `IPerson` with a given name on a given bugtracker.

        :param name: The name of the person on the bugtracker in
            `bugtracker`.
        :param bugtracker: The `IBugTracker` against which the `IPerson`
            to be returned is registered with `name`.
        :return: an `IBugTrackerPerson`.
        """

    def linkPersonToBugTracker(name, bugtracker, person):
        """Link a Person to a BugTracker using a given name.

        :param name: The name used for person on bugtracker.
        :param bugtracker: The `IBugTracker` to which person should be linked.
        :param person: The `IPerson` to link to bugtracker.
        :raise BugTrackerNameAlreadyTaken: If `name` has already been
            used to link a person to `bugtracker`.
        :return: An `IBugTrackerPerson`.
        """
